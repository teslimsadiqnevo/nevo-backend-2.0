from datetime import date, datetime, time
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.content import Lesson
from nevo.db.models.frontend_support import Concept
from nevo.db.models.mastery import StudentConceptMastery
from nevo.db.models.signal_event import LessonSession, SignalEvent
from nevo.domain.signal_events.vocabulary import LessonCompletionStatus, SignalEventType
from nevo.parents.entities import GrowthSignals

CONFIDENT_MASTERY = 0.7
"""Where a concept counts as understood rather than merely practised."""

SELF_ADJUSTMENT_EVENTS = (
    SignalEventType.SIMPLIFY_TRIGGER,
    SignalEventType.EXPAND_TRIGGER,
    SignalEventType.SLOWER_TRIGGER,
)
"""A learner asking for a different explanation is a learner noticing."""


class SqlAlchemyParentInsightRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def growth_signals(
        self,
        *,
        student_id: UUID,
        window_start: date,
        window_end: date,
    ) -> GrowthSignals:
        start = datetime.combine(window_start, time.min).astimezone()
        end = datetime.combine(window_end, time.max).astimezone()
        async with self._sessions() as session:
            totals = (
                await session.execute(
                    select(
                        func.count(LessonSession.id),
                        func.count(LessonSession.id).filter(
                            LessonSession.completion_status
                            == LessonCompletionStatus.COMPLETED
                        ),
                        func.count(LessonSession.id).filter(
                            LessonSession.completion_status == LessonCompletionStatus.EXITED
                        ),
                    ).where(
                        LessonSession.student_id == student_id,
                        LessonSession.started_at >= start,
                        LessonSession.started_at <= end,
                    )
                )
            ).one()
            events = (
                await session.execute(
                    select(
                        func.count(SignalEvent.id).filter(
                            SignalEvent.event_type == SignalEventType.EXIT_ATTEMPT
                        ),
                        func.count(SignalEvent.id).filter(
                            SignalEvent.event_type.in_(SELF_ADJUSTMENT_EVENTS)
                        ),
                        func.count(SignalEvent.id).filter(
                            SignalEvent.event_type == SignalEventType.COMPREHENSION_RESPONSE
                        ),
                    ).where(
                        SignalEvent.student_id == student_id,
                        SignalEvent.timestamp >= start,
                        SignalEvent.timestamp <= end,
                    )
                )
            ).one()
            subjects = int(
                await session.scalar(
                    select(func.count(func.distinct(Lesson.subject)))
                    .select_from(LessonSession)
                    .join(Lesson, Lesson.id == LessonSession.lesson_id)
                    .where(
                        LessonSession.student_id == student_id,
                        LessonSession.started_at >= start,
                        LessonSession.started_at <= end,
                        Lesson.subject.is_not(None),
                    )
                )
                or 0
            )
            mastery = (
                await session.execute(
                    select(
                        func.count(StudentConceptMastery.id),
                        func.count(StudentConceptMastery.id).filter(
                            StudentConceptMastery.mastery_probability_concept
                            >= CONFIDENT_MASTERY
                        ),
                        func.sum(StudentConceptMastery.practice_count).filter(
                            StudentConceptMastery.mastery_probability_concept
                            >= CONFIDENT_MASTERY
                        ),
                    ).where(
                        StudentConceptMastery.student_id == student_id,
                        StudentConceptMastery.last_updated >= start,
                        StudentConceptMastery.last_updated <= end,
                    )
                )
            ).one()

        practised, confident, practice_total = mastery
        return GrowthSignals(
            sessions=int(totals[0] or 0),
            completed_sessions=int(totals[1] or 0),
            exited_sessions=int(totals[2] or 0),
            exit_attempts=int(events[0] or 0),
            self_adjustments=int(events[1] or 0),
            comprehension_responses=int(events[2] or 0),
            subjects_touched=subjects,
            concepts_practised=int(practised or 0),
            concepts_confident=int(confident or 0),
            practice_per_confident_concept=(
                float(practice_total) / int(confident)
                if confident and practice_total
                else None
            ),
        )

    async def subject_count_unavailable(self) -> bool:
        """Whether any lesson carries a subject at all.

        Lesson.subject is nullable and often unset, and a "connecting ideas"
        line drawn from nothing would be a confident sentence about a child
        based on missing data.
        """
        async with self._sessions() as session:
            any_subject = await session.scalar(
                select(Concept.id).where(Concept.subject.is_not(None)).limit(1)
            )
        return any_subject is None
