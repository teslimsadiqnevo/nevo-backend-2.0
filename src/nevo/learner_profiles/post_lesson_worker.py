import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.attention_flags.service import AttentionFlagDetectionService
from nevo.db.models.product import PostLessonProcessing
from nevo.learner_profiles.profile_updates import PostLessonProfileUpdateService

MAX_ATTEMPTS = 5


class PostLessonProcessingWorker:
    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        profile_service: PostLessonProfileUpdateService,
        flag_service: AttentionFlagDetectionService,
        poll_seconds: float = 3,
    ) -> None:
        self._sessions = sessions
        self._profile_service = profile_service
        self._flag_service = flag_service
        self._poll_seconds = poll_seconds
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="post-lesson-processing")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def enqueue(
        self,
        *,
        session_id: UUID,
        student_id: UUID,
        completed_at: datetime | None = None,
    ) -> str:
        now = datetime.now(UTC)
        statement = (
            insert(PostLessonProcessing)
            .values(
                session_id=session_id,
                student_id=student_id,
                completed_at=completed_at or now,
                status="pending",
                next_attempt_at=now,
            )
            .on_conflict_do_nothing(index_elements=[PostLessonProcessing.session_id])
        )
        async with self._sessions.begin() as session:
            await session.execute(statement)
            record = await session.get(PostLessonProcessing, session_id)
            return record.status if record is not None else "pending"

    async def process_next(self) -> bool:
        job = await self._claim()
        if job is None:
            return False
        session_id, student_id, profile_updated, flags_evaluated = job
        try:
            if not profile_updated:
                await self._profile_service.update_after_lesson(
                    student_id=student_id,
                    lesson_session_id=session_id,
                    requested_by_user_id=student_id,
                )
                await self._mark_stage(session_id, profile_updated=True)
            if not flags_evaluated:
                await self._flag_service.evaluate_student(
                    student_id=student_id,
                    requested_by_user_id=student_id,
                )
                await self._mark_stage(session_id, flags_evaluated=True)
            await self._complete(session_id)
        except Exception as error:
            await self._retry(session_id, error)
        return True

    async def _run(self) -> None:
        while True:
            worked = await self.process_next()
            if not worked:
                await asyncio.sleep(self._poll_seconds)

    async def _claim(self) -> tuple[UUID, UUID, bool, bool] | None:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            record = await session.scalar(
                select(PostLessonProcessing)
                .where(
                    PostLessonProcessing.attempt_count < MAX_ATTEMPTS,
                    PostLessonProcessing.next_attempt_at <= now,
                    or_(
                        PostLessonProcessing.status.in_(("pending", "failed")),
                        PostLessonProcessing.status == "processing",
                    ),
                )
                .order_by(PostLessonProcessing.next_attempt_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if record is None:
                return None
            record.status = "processing"
            record.attempt_count += 1
            record.next_attempt_at = now + timedelta(minutes=10)
            record.last_error = None
            return (
                record.session_id,
                record.student_id,
                record.profile_updated,
                record.flags_evaluated,
            )

    async def _mark_stage(self, session_id: UUID, **values: bool) -> None:
        async with self._sessions.begin() as session:
            record = await session.get(PostLessonProcessing, session_id, with_for_update=True)
            if record is not None:
                for field, value in values.items():
                    setattr(record, field, value)

    async def _complete(self, session_id: UUID) -> None:
        async with self._sessions.begin() as session:
            record = await session.get(PostLessonProcessing, session_id, with_for_update=True)
            if record is not None:
                record.status = "completed"
                record.processed_at = datetime.now(UTC)
                record.last_error = None

    async def _retry(self, session_id: UUID, error: Exception) -> None:
        async with self._sessions.begin() as session:
            record = await session.get(PostLessonProcessing, session_id, with_for_update=True)
            if record is None:
                return
            record.status = (
                "permanently_failed"
                if record.attempt_count >= MAX_ATTEMPTS
                else "failed"
            )
            delay_minutes = min(60, 2 ** max(0, record.attempt_count - 1))
            record.next_attempt_at = datetime.now(UTC) + timedelta(minutes=delay_minutes)
            record.last_error = str(error)[:1000]
