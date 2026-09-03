from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.frontend_support import Concept
from nevo.db.models.mastery import StudentConceptScheduling
from nevo.scheduler.entities import ConceptSchedule
from nevo.scheduler.fsrs import refresh_due_date, retrievability


class SqlAlchemySchedulerRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def schedule(
        self,
        *,
        student_id: UUID,
        concept_id: UUID,
        now: datetime,
    ) -> ConceptSchedule | None:
        async with self._sessions() as session:
            record = await session.scalar(
                select(StudentConceptScheduling).where(
                    StudentConceptScheduling.student_id == student_id,
                    StudentConceptScheduling.concept_id == concept_id,
                )
            )
        return _schedule_from_record(record, now=now) if record else None

    async def due_reviews(
        self,
        *,
        student_id: UUID,
        now: datetime,
    ) -> tuple[ConceptSchedule, ...]:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(StudentConceptScheduling, Concept.lesson_id)
                    .outerjoin(Concept, Concept.id == StudentConceptScheduling.concept_id)
                    .where(
                        StudentConceptScheduling.student_id == student_id,
                        StudentConceptScheduling.next_review_due <= now,
                    )
                    .order_by(StudentConceptScheduling.next_review_due)
                )
            ).all()
        return tuple(
            _schedule_from_record(row, now=now, lesson_id=lesson_id)
            for row, lesson_id in rows
        )

    async def save(self, schedule: ConceptSchedule) -> ConceptSchedule:
        async with self._sessions.begin() as session:
            record = await session.scalar(
                select(StudentConceptScheduling).where(
                    StudentConceptScheduling.student_id == schedule.student_id,
                    StudentConceptScheduling.concept_id == schedule.concept_id,
                )
            )
            values = {
                "stability": schedule.stability,
                "difficulty": schedule.difficulty,
                "last_review": schedule.last_review,
                "review_count": schedule.review_count,
                "next_review_due": schedule.next_review_due,
            }
            if record is None:
                session.add(
                    StudentConceptScheduling(
                        student_id=schedule.student_id,
                        concept_id=schedule.concept_id,
                        **values,
                    )
                )
            else:
                await session.execute(
                    update(StudentConceptScheduling)
                    .where(StudentConceptScheduling.id == record.id)
                    .values(**values)
                )
        return schedule

    async def all_schedules(self, *, now: datetime) -> tuple[ConceptSchedule, ...]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(StudentConceptScheduling).order_by(
                        StudentConceptScheduling.student_id,
                        StudentConceptScheduling.concept_id,
                    )
                )
            ).all()
        return tuple(_schedule_from_record(row, now=now) for row in rows)


def _schedule_from_record(
    record: StudentConceptScheduling,
    *,
    now: datetime,
    lesson_id: UUID | None = None,
) -> ConceptSchedule:
    last_review = record.last_review
    if last_review.tzinfo is None:
        last_review = last_review.replace(tzinfo=UTC)
    current = ConceptSchedule(
        student_id=record.student_id,
        concept_id=record.concept_id,
        stability=record.stability,
        difficulty=record.difficulty,
        retrievability=retrievability(
            elapsed_days=(now - last_review).total_seconds() / 86_400,
            stability=record.stability,
        ),
        last_review=last_review,
        review_count=record.review_count,
        next_review_due=record.next_review_due,
        lesson_id=lesson_id,
    )
    return refresh_due_date(current=current, now=now)
