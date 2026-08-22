from typing import Protocol
from uuid import UUID

from nevo.intelligence.accommodations import UdlAccommodationInferenceEngine
from nevo.intelligence.entities import AccommodationAnalysis, BehaviourPatternAggregate


class AccommodationPatternRepository(Protocol):
    async def aggregate_for_student(
        self,
        *,
        student_id: UUID,
        lesson_limit: int = 5,
    ) -> BehaviourPatternAggregate: ...


class AccommodationInferenceService:
    def __init__(
        self,
        *,
        repository: AccommodationPatternRepository,
        engine: UdlAccommodationInferenceEngine,
    ) -> None:
        self._repository = repository
        self._engine = engine

    async def analyse_student(
        self,
        *,
        student_id: UUID,
    ) -> AccommodationAnalysis:
        aggregate = await self._repository.aggregate_for_student(student_id=student_id)
        return self._engine.analyse(student_id=student_id, aggregate=aggregate)
