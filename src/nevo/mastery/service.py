from typing import Protocol
from uuid import UUID

from nevo.mastery.engine import HybridAktMasteryEngine
from nevo.mastery.entities import (
    BaselineMasterySeed,
    ConceptMasteryAggregate,
    MasteryState,
    MasteryUpdate,
    MasteryUpdateResult,
)


class MasteryRepository(Protocol):
    async def state(
        self,
        *,
        student_id: UUID,
        concept_id: UUID,
    ) -> MasteryState | None: ...

    async def baseline_seed(self, student_id: UUID) -> BaselineMasterySeed: ...

    async def related_mastery(
        self,
        *,
        student_id: UUID,
        concept_ids: tuple[UUID, ...],
    ) -> dict[UUID, float]: ...

    async def save(self, state: MasteryState) -> MasteryState: ...

    async def student_mastery(self, student_id: UUID) -> tuple[MasteryState, ...]: ...

    async def class_mastery(
        self,
        class_id: UUID,
    ) -> tuple[ConceptMasteryAggregate, ...]: ...

    async def school_mastery(
        self,
        school_id: UUID,
    ) -> tuple[ConceptMasteryAggregate, ...]: ...


class MasteryService:
    def __init__(
        self,
        *,
        repository: MasteryRepository,
        engine: HybridAktMasteryEngine,
    ) -> None:
        self._repository = repository
        self._engine = engine

    async def update(self, interaction: MasteryUpdate) -> MasteryUpdateResult:
        state = await self._repository.state(
            student_id=interaction.student_id,
            concept_id=interaction.concept_id,
        )
        if state is None:
            seed = await self._repository.baseline_seed(interaction.student_id)
            state = self._engine.initial_state(
                student_id=interaction.student_id,
                concept_id=interaction.concept_id,
                seed=seed,
                related_concept_ids=interaction.related_concept_ids,
            )
        related_mastery = await self._repository.related_mastery(
            student_id=interaction.student_id,
            concept_ids=interaction.related_concept_ids,
        )
        result = self._engine.update(
            state=state,
            interaction=interaction,
            related_mastery=related_mastery,
        )
        await self._repository.save(result.state)
        return result

    async def student_mastery(self, student_id: UUID) -> tuple[MasteryState, ...]:
        return await self._repository.student_mastery(student_id)

    async def class_mastery(
        self,
        class_id: UUID,
    ) -> tuple[ConceptMasteryAggregate, ...]:
        return await self._repository.class_mastery(class_id)

    async def school_mastery(
        self,
        school_id: UUID,
    ) -> tuple[ConceptMasteryAggregate, ...]:
        return await self._repository.school_mastery(school_id)
