from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from nevo.domain.ask_nevo.vocabulary import (
    AskNevoMessageAuthor,
    AskNevoQuestionCategory,
    AskNevoRole,
)


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
    #: The conversation this answer belongs to. Send it back on the next
    #: question to continue the same chat.
    thread_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ThreadSummary:
    """One past conversation, as a list of them shows it."""

    thread_id: UUID
    title: str
    role: AskNevoRole
    message_count: int
    last_message_at: datetime
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ThreadMessage:
    message_id: UUID
    author: AskNevoMessageAuthor
    sequence: int
    body: str
    blocks: tuple[dict[str, Any], ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ThreadTranscript:
    thread_id: UUID
    title: str
    role: AskNevoRole
    created_at: datetime
    messages: tuple[ThreadMessage, ...]
