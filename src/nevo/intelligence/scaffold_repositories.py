from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.mastery import ScaffoldProblemLog, StudentConceptScaffoldState
from nevo.intelligence.entities import (
    ScaffoldConceptState,
    ScaffoldDecision,
    ScaffoldProblemLogEntry,
)


class SqlAlchemyScaffoldRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def state(
        self,
        *,
        student_id: UUID,
        concept_id: UUID,
    ) -> ScaffoldConceptState | None:
        async with self._sessions() as session:
            record = await session.scalar(
                select(StudentConceptScaffoldState).where(
                    StudentConceptScaffoldState.student_id == student_id,
                    StudentConceptScaffoldState.concept_id == concept_id,
                )
            )
        return _state_from_record(record) if record else None

    async def save_decision(
        self,
        *,
        decision: ScaffoldDecision,
        log: ScaffoldProblemLogEntry,
    ) -> ScaffoldDecision:
        async with self._sessions.begin() as session:
            record = await session.scalar(
                select(StudentConceptScaffoldState).where(
                    StudentConceptScaffoldState.student_id
                    == decision.state.student_id,
                    StudentConceptScaffoldState.concept_id
                    == decision.state.concept_id,
                )
            )
            values = {
                "current_intensity": decision.state.current_intensity,
                "consecutive_correct": decision.state.consecutive_correct,
                "response_time_improvement_streak": (
                    decision.state.response_time_improvement_streak
                ),
                "reduced_hint_streak": decision.state.reduced_hint_streak,
                "last_response_time_ms": decision.state.last_response_time_ms,
                "last_hint_count": decision.state.last_hint_count,
            }
            if record is None:
                session.add(
                    StudentConceptScaffoldState(
                        student_id=decision.state.student_id,
                        concept_id=decision.state.concept_id,
                        **values,
                    )
                )
            else:
                await session.execute(
                    update(StudentConceptScaffoldState)
                    .where(StudentConceptScaffoldState.id == record.id)
                    .values(**values)
                )
            session.add(
                ScaffoldProblemLog(
                    student_id=log.student_id,
                    concept_id=log.concept_id,
                    problem_id=log.problem_id,
                    scaffold_intensity=log.scaffold_intensity,
                    outcome=log.outcome,
                    response_time_ms=log.response_time_ms,
                    expected_response_time_ms=log.expected_response_time_ms,
                    hint_count=log.hint_count,
                    next_scaffold_intensity=log.next_scaffold_intensity,
                    level_changed=log.level_changed,
                    change_reason=log.change_reason,
                )
            )
        return decision

    async def logs(
        self,
        *,
        student_id: UUID,
        concept_id: UUID | None = None,
        limit: int = 100,
    ) -> tuple[ScaffoldProblemLogEntry, ...]:
        statement = (
            select(ScaffoldProblemLog)
            .where(ScaffoldProblemLog.student_id == student_id)
            .order_by(ScaffoldProblemLog.created_at.desc())
            .limit(limit)
        )
        if concept_id is not None:
            statement = statement.where(ScaffoldProblemLog.concept_id == concept_id)
        async with self._sessions() as session:
            rows = (await session.scalars(statement)).all()
        return tuple(_log_from_record(row) for row in rows)


def _state_from_record(record: StudentConceptScaffoldState) -> ScaffoldConceptState:
    return ScaffoldConceptState(
        student_id=record.student_id,
        concept_id=record.concept_id,
        current_intensity=record.current_intensity,
        consecutive_correct=record.consecutive_correct,
        response_time_improvement_streak=record.response_time_improvement_streak,
        reduced_hint_streak=record.reduced_hint_streak,
        last_response_time_ms=record.last_response_time_ms,
        last_hint_count=record.last_hint_count,
    )


def _log_from_record(record: ScaffoldProblemLog) -> ScaffoldProblemLogEntry:
    return ScaffoldProblemLogEntry(
        student_id=record.student_id,
        concept_id=record.concept_id,
        problem_id=record.problem_id,
        scaffold_intensity=record.scaffold_intensity,
        outcome=record.outcome,
        response_time_ms=record.response_time_ms,
        expected_response_time_ms=record.expected_response_time_ms,
        hint_count=record.hint_count,
        next_scaffold_intensity=record.next_scaffold_intensity,
        level_changed=record.level_changed,
        change_reason=record.change_reason,
    )
