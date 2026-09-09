from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.account import School, User
from nevo.db.models.ask_nevo import AskNevoThread
from nevo.domain.accounts.vocabulary import UserRole, UserStatus
from nevo.retention.anonymisation import anonymise_student

DEFAULT_BATCH_SIZE = 200


@dataclass(frozen=True, slots=True)
class RetentionSweepResult:
    scanned: int
    anonymised: int
    chats_removed: int = 0

    def summary(self) -> str:
        return (
            f"anonymised {self.anonymised} of {self.scanned} expired student "
            f"records, removed {self.chats_removed} expired chats"
        )


class RetentionService:
    """Enforces each school's data-retention window without an admin acting.

    A student who left the school is anonymised once their school's
    ``data_retention_days`` have elapsed since deactivation. Already-anonymised
    rows are skipped, so the sweep is safe to run as often as you like.
    """

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def sweep(
        self,
        *,
        now: datetime | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> RetentionSweepResult:
        current_time = now or datetime.now(UTC)
        async with self._sessions.begin() as session:
            rows = (
                await session.execute(
                    select(User, School.data_retention_days)
                    .join(School, School.id == User.school_id)
                    .where(
                        User.role == UserRole.STUDENT,
                        User.status == UserStatus.DEACTIVATED,
                        User.deactivated_at.is_not(None),
                        User.anonymised_at.is_(None),
                    )
                    .order_by(User.deactivated_at)
                    .limit(batch_size)
                    .with_for_update(of=User, skip_locked=True)
                )
            ).all()

            anonymised = 0
            for student, retention_days in rows:
                if self._is_expired(student.deactivated_at, retention_days, current_time):
                    anonymise_student(student, now=current_time)
                    anonymised += 1
        chats_removed = await self._sweep_chats(current_time)
        return RetentionSweepResult(
            scanned=len(rows),
            anonymised=anonymised,
            chats_removed=chats_removed,
        )

    async def _sweep_chats(self, now: datetime) -> int:
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
                            AskNevoThread.last_message_at
                            < now
                            - func.make_interval(
                                0,
                                0,
                                0,
                                func.coalesce(School.data_retention_days, 365),
                            ),
                        )
                    )
                    .limit(DEFAULT_BATCH_SIZE)
                )
            )
            if expired:
                await session.execute(
                    delete(AskNevoThread).where(AskNevoThread.id.in_(expired))
                )
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
