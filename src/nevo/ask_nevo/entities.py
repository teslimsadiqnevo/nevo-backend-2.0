from dataclasses import dataclass
from uuid import UUID

from nevo.domain.ask_nevo.vocabulary import AskNevoQuestionCategory, AskNevoRole


@dataclass(frozen=True, slots=True)
class AskNevoContextIds:
    student_id: UUID | None = None
    class_id: UUID | None = None
    lesson_id: UUID | None = None
    segment_id: str | None = None
    thread_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class AskNevoRequest:
    role: AskNevoRole
    current_page: str
    context_ids: AskNevoContextIds
    question: str


@dataclass(frozen=True, slots=True)
class AskNevoContext:
    payload: dict[str, object]
    student_id_for_gateway: UUID | None


@dataclass(frozen=True, slots=True)
class AskNevoResponse:
    answer: str
    question_category: AskNevoQuestionCategory
    interaction_id: UUID
    ai_gateway_call_id: UUID
