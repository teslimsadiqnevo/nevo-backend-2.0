from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from nevo.domain.parents.vocabulary import GrowthDimension, GrowthTrend


@dataclass(frozen=True, slots=True)
class GrowthSignals:
    """Raw counts for one learner over one window.

    Held separately from the prose so the numbers never leave the backend:
    the parent screen is designed to carry no scores, and the way to keep
    that promise is to not send any.
    """

    sessions: int
    completed_sessions: int
    exited_sessions: int
    exit_attempts: int
    self_adjustments: int
    comprehension_responses: int
    subjects_touched: int
    concepts_practised: int
    concepts_confident: int
    practice_per_confident_concept: float | None


@dataclass(frozen=True, slots=True)
class GrowthStatement:
    dimension: GrowthDimension
    trend: GrowthTrend
    statement: str


@dataclass(frozen=True, slots=True)
class GrowthNarrative:
    student_id: UUID
    student_first_name: str
    headline: str
    summary: str
    statements: tuple[GrowthStatement, ...]
    period_start: date
    period_end: date
    comparison_start: date
    comparison_end: date
    generated_at: datetime
