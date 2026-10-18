from dataclasses import dataclass

from nevo.domain.learner_profiles.vocabulary import (
    ConfidenceLevel,
)

ProfileValue = int | None


@dataclass(frozen=True, slots=True)
class ObservedActivity:
    activity_number: int
    metrics: dict[str, float | int | str | bool]


@dataclass(frozen=True, slots=True)
class DimensionInference:
    dimension: str
    value: ProfileValue
    confidence: ConfidenceLevel
    evidence_count: int
    notes: tuple[str, ...] = ()
