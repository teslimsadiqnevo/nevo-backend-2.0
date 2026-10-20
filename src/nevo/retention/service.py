import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.account import School, User
from nevo.db.models.ask_nevo import AskNevoThread
from nevo.db.models.retention import LearnerPurgeReceipt
from nevo.domain.accounts.vocabulary import UserRole
from nevo.domain.ask_nevo.vocabulary import AskNevoRole
from nevo.retention.purge import clear_identity, delete_learner_records

DEFAULT_BATCH_SIZE = 200


@dataclass(frozen=True, slots=True)
class RetentionSweepResult:
    scanned: int
    anonymised: int
    chats_removed: int = 0
    failed: int = 0

    def summary(self) -> str:
        return (
            f"anonymised {self.anonymised} of {self.scanned} expired student "
            f"records, removed {self.chats_removed} expired chats; "
            f"{self.failed} purges require retry"
        )


class RetentionService:
    """Erase linked records and managed files after the recorded purpose ends.

    Earlier name-only anonymisation does not count as a completed purge.
    Storage failures preserve a retry receipt rather than reporting success.
    """

    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], *, storage=None, receipt_key=None
    ) -> None:
        self._sessions = sessions
        self._storage = storage
        self._receipt_key = receipt_key

    async def sweep(
        self,
        *,
        now: datetime | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> RetentionSweepResult:
        current_time = now or datetime.now(UTC)
        from nevo.consent.age_assurance import prepare_pending_holds

        await prepare_pending_holds(self._sessions, current_time)
        async with self._sessions() as session:
            wanted = list(
                await session.scalars(
                    select(User.id)
                    .where(
                        User.role == UserRole.STUDENT,
                        User.retention_due_at <= current_time,
                        User.retention_purged_at.is_(None),
                    )
                    .order_by(User.retention_due_at)
                    .limit(batch_size)
                )
            )
        anonymised = failed = 0
        for student_id in wanted:
            try:
                if await self._purge(student_id, current_time):
                    anonymised += 1
            except Exception:
                failed += 1
                # A partial deletion is retryable, never reported as completed.
                async with self._sessions.begin() as session:
                    record = await session.scalar(
                        select(LearnerPurgeReceipt).where(
                            LearnerPurgeReceipt.student_id == student_id
                        )
                    )
                    if record:
                        record.status, record.error_code = "retry", "purge_incomplete"
        chats_removed = await self._sweep_chats(current_time)
        return RetentionSweepResult(
            scanned=len(wanted),
            anonymised=anonymised,
            chats_removed=chats_removed,
            failed=failed,
        )

    async def _purge(self, student_id, now):
        if not self._receipt_key:
            raise RuntimeError("Retention audit key is unavailable")
        async with self._sessions.begin() as session:
            student = await session.get(User, student_id, with_for_update=True)
            if (
                not student
                or student.retention_purged_at
                or not student.retention_due_at
                or student.retention_due_at > now
            ):
                return False
            digest = hmac.new(
                self._receipt_key.encode(), f"retention-v1:{student_id}".encode(), hashlib.sha256
            ).hexdigest()
            job = await session.scalar(
                select(LearnerPurgeReceipt).where(LearnerPurgeReceipt.subject_digest == digest)
            )
            if job is None:
                job = LearnerPurgeReceipt(
                    student_id=student_id,
                    school_id=student.school_id,
                    subject_digest=digest,
                    object_paths=[],
                    counts={},
                )
                session.add(job)
            # Commit the job before external deletion so a crash is observable and retryable.
        if self._storage is None or not self._storage.configured:
            raise RuntimeError("Retention storage is unavailable")
        async with self._sessions.begin() as session:
            student = await session.get(User, student_id, with_for_update=True)
            if student.retention_purged_at or student.retention_due_at > now:
                return False
            job = await session.scalar(
                select(LearnerPurgeReceipt)
                .where(LearnerPurgeReceipt.student_id == student_id)
                .with_for_update()
            )
            from nevo.db.models.account import ConsentRecord

            paths = set(job.object_paths or [])
            paths.update(await self._storage.list_paths(f"images/profiles/{student_id}"))
            paths.update(await self._storage.list_paths(f"consent/written/{student_id}"))
            image_path = (student.preferences or {}).get("profileImagePath")
            if isinstance(image_path, str) and image_path.startswith(
                f"images/profiles/{student_id}/"
            ):
                paths.add(image_path)
            paths.update(
                path
                for path in await session.scalars(
                    select(ConsentRecord.evidence_storage_path).where(
                        ConsentRecord.subject_user_id == student_id
                    )
                )
                if path
            )
            for path in paths:
                if not any(
                    path.startswith(prefix)
                    for prefix in (
                        f"images/profiles/{student_id}/",
                        f"consent/written/{student_id}/",
                    )
                ):
                    raise RuntimeError("Retention object ownership could not be established")
                await self._storage.delete(path)
            counts = await delete_learner_records(session, student)
            clear_identity(student, now)
            job.status, job.error_code, job.completed_at = "completed", None, now
            job.student_id, job.object_paths, job.counts = None, [], counts
        return True

    async def _sweep_chats(self, now: datetime) -> int:
        removed = 0
        while True:
            batch = await self._sweep_chat_batch(now)
            removed += batch
            if batch < DEFAULT_BATCH_SIZE:
                return removed

    async def _sweep_chat_batch(self, now: datetime) -> int:
        """Remove Ask Nevo conversations past their school's window.

        A chat holds a child's own words, which is about as sensitive as this
        product gets. It expires on the same clock as everything else rather
        than sitting there indefinitely, and one the asker deleted goes at the
        next sweep regardless of age.
        """
        async with self._sessions.begin() as session:
            expired = list(
                await session.scalars(
                    select(AskNevoThread.id)
                    .outerjoin(School, School.id == AskNevoThread.school_id)
                    .where(
                        or_(
                            AskNevoThread.deleted_at.is_not(None),
                            and_(
                                AskNevoThread.role == AskNevoRole.TEACHER,
                                AskNevoThread.created_at <= now - timedelta(days=90),
                            ),
                            AskNevoThread.last_message_at
                            < now
                            - func.make_interval(
                                0,
                                0,
                                0,
                                func.least(func.coalesce(School.data_retention_days, 180), 180),
                            ),
                        )
                    )
                    .limit(DEFAULT_BATCH_SIZE)
                )
            )
            if expired:
                await session.execute(delete(AskNevoThread).where(AskNevoThread.id.in_(expired)))
        return len(expired)

    @staticmethod
    def _is_expired(
        deactivated_at: datetime | None,
        retention_days: int,
        now: datetime,
    ) -> bool:
        if deactivated_at is None:
            return False
        if deactivated_at.tzinfo is None:
            deactivated_at = deactivated_at.replace(tzinfo=UTC)
        return now - deactivated_at >= timedelta(days=retention_days)
