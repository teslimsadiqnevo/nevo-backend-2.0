from typing import Protocol
from uuid import UUID

from nevo.intelligence.entities import (
    ScaffoldConceptState,
    ScaffoldDecision,
    ScaffoldProblemAttempt,
    ScaffoldProblemLogEntry,
)
from nevo.intelligence.scaffolds import ProgressiveScaffoldFadingEngine


class ScaffoldRepository(Protocol):
    async def state(
        self,
        *,
        student_id: UUID,
        concept_id: UUID,
    ) -> ScaffoldConceptState | None: ...

    async def save_decision(
        self,
        *,
        decision: ScaffoldDecision,
        log: ScaffoldProblemLogEntry,
    ) -> ScaffoldDecision: ...

    async def logs(
        self,
        *,
        student_id: UUID,
        concept_id: UUID | None = None,
        limit: int = 100,
    ) -> tuple[ScaffoldProblemLogEntry, ...]: ...


class ScaffoldFadingService:
    def __init__(
        self,
        *,
        repository: ScaffoldRepository,
        engine: ProgressiveScaffoldFadingEngine,
    ) -> None:
        self._repository = repository
        self._engine = engine

    async def current_state(
        self,
        *,
        student_id: UUID,
        concept_id: UUID,
    ) -> ScaffoldConceptState:
        state = await self._repository.state(
            student_id=student_id,
            concept_id=concept_id,
        )
        return state or self._engine.initial_state(
            student_id=student_id,
            concept_id=concept_id,
        )

    async def record_attempt(self, attempt: ScaffoldProblemAttempt) -> ScaffoldDecision:
        state = await self.current_state(
            student_id=attempt.student_id,
            concept_id=attempt.concept_id,
        )
        decision = self._engine.record_attempt(state=state, attempt=attempt)
        log = ScaffoldProblemLogEntry(
            student_id=attempt.student_id,
            concept_id=attempt.concept_id,
            problem_id=attempt.problem_id,
            scaffold_intensity=decision.previous_intensity,
            outcome=decision.outcome,
            response_time_ms=attempt.response_time_ms,
            expected_response_time_ms=attempt.expected_response_time_ms,
            hint_count=attempt.hint_count,
            next_scaffold_intensity=decision.next_intensity,
            level_changed=decision.level_changed,
            change_reason=decision.change_reason,
        )
        return await self._repository.save_decision(decision=decision, log=log)

    async def history(
        self,
        *,
        student_id: UUID,
        concept_id: UUID | None = None,
        limit: int = 100,
    ) -> tuple[ScaffoldProblemLogEntry, ...]:
        return await self._repository.logs(
            student_id=student_id,
            concept_id=concept_id,
            limit=limit,
        )
