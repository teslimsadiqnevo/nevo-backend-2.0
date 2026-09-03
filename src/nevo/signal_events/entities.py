from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from nevo.domain.signal_events.vocabulary import (
    LessonCompletionStatus,
    SignalEventType,
)


@dataclass(frozen=True, slots=True)
class LessonSessionSnapshot:
    id: UUID
    student_id: UUID
    lesson_id: UUID | None
    started_at: datetime
    ended_at: datetime | None
    completion_status: LessonCompletionStatus
    exit_position: str | None
    break_count: int
    proactive_adjustments_count: int
    session_type: str = "lesson"


@dataclass(frozen=True, slots=True)
class SignalEventDraft:
    student_id: UUID
    session_id: UUID
    event_type: SignalEventType
    event_data: dict[str, object]
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class SignalIngestionBatch:
    session: LessonSessionSnapshot
    events: tuple[SignalEventDraft, ...]


@dataclass(frozen=True, slots=True)
class SignalIngestionReceipt:
    session_id: UUID
    accepted_events: int
