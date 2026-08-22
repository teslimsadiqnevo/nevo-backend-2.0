from dataclasses import dataclass
from uuid import UUID

from nevo.domain.mastery.vocabulary import FailureAttribution


@dataclass(frozen=True, slots=True)
class BaselineMasterySeed:
    concept_probability: float
    reading_probability: float
    source: str


@dataclass(frozen=True, slots=True)
class MasteryState:
    student_id: UUID
    concept_id: UUID
    mastery_probability_concept: float
    mastery_probability_reading: float
    attention_weights: dict[str, float]
    guess_probability: float
    slip_probability: float
    practice_count: int
    last_response_correct: bool | None
    last_failure_attribution: FailureAttribution
    seeding_source: str = "default"


@dataclass(frozen=True, slots=True)
class MasteryUpdate:
    student_id: UUID
    concept_id: UUID
    response_correct: bool
    item_text_density: float
    related_concept_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class MasteryUpdateResult:
    state: MasteryState
    attention_transfer: float
    recommended_modality_shift: bool


@dataclass(frozen=True, slots=True)
class ConceptMasteryAggregate:
    concept_id: UUID
    student_count: int
    mastery_probability_concept: float
    mastery_probability_reading: float
