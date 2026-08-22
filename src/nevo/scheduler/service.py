from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from nevo.scheduler.entities import ConceptSchedule, ReviewResult
from nevo.scheduler.fsrs import initial_schedule, update_schedule


class SchedulerRepository(Protocol):
    async def schedule(
        self,
        *,
        student_id: UUID,
        concept_id: UUID,
        now: datetime,
    ) -> ConceptSchedule | None: ...

    async def due_reviews(
        self,
        *,
        student_id: UUID,
        now: datetime,
    ) -> tuple[ConceptSchedule, ...]: ...

    async def save(self, schedule: ConceptSchedule) -> ConceptSchedule: ...

    async def all_schedules(self, *, now: datetime) -> tuple[ConceptSchedule, ...]: ...


class FsrsSchedulerService:
    def __init__(self, repository: SchedulerRepository) -> None:
        self._repository = repository

    async def due_reviews(
        self,
        *,
        student_id: UUID,
        now: datetime | None = None,
    ) -> tuple[ConceptSchedule, ...]:
        return await self._repository.due_reviews(
            student_id=student_id,
            now=now or datetime.now(UTC),
        )

    async def record_review(
        self,
        *,
        student_id: UUID,
        concept_id: UUID,
        recall_successful: bool,
        reviewed_at: datetime | None = None,
    ) -> ReviewResult:
        now = reviewed_at or datetime.now(UTC)
        current = await self._repository.schedule(
            student_id=student_id,
            concept_id=concept_id,
            now=now,
        )
        if current is None:
            schedule = initial_schedule(
                student_id=student_id,
                concept_id=concept_id,
                recall_successful=recall_successful,
                reviewed_at=now,
            )
        else:
            schedule = update_schedule(
                current=current,
                recall_successful=recall_successful,
                reviewed_at=now,
            )
        await self._repository.save(schedule)
        return ReviewResult(schedule=schedule, recall_successful=recall_successful)

    async def refresh_all_due_dates(
        self,
        *,
        now: datetime | None = None,
    ) -> tuple[ConceptSchedule, ...]:
        current_time = now or datetime.now(UTC)
        schedules = await self._repository.all_schedules(now=current_time)
        refreshed = []
        for schedule in schedules:
            await self._repository.save(schedule)
            refreshed.append(schedule)
        return tuple(refreshed)
