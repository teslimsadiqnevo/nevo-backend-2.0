from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ConceptSchedule:
    student_id: UUID
    concept_id: UUID
    stability: float
    difficulty: float
    retrievability: float
    last_review: datetime
    review_count: int
    next_review_due: datetime
    lesson_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ReviewResult:
    schedule: ConceptSchedule
    recall_successful: bool
