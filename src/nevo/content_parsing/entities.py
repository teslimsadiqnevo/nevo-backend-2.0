from dataclasses import dataclass, field
from uuid import UUID

from nevo.domain.intelligence.vocabulary import (
    ContentModality,
    ContentParseStatus,
    LessonContentType,
    LessonSourceType,
)


@dataclass(frozen=True, slots=True)
class SourcePage:
    page_number: int
    text: str


@dataclass(frozen=True, slots=True)
class ContentParseRequest:
    title: str
    source_type: LessonSourceType
    source_text: str | None = None
    pages: tuple[SourcePage, ...] = ()
    source_metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ParsedLessonSegment:
    segment_key: str
    content_type: LessonContentType
    sequence_order: int
    title: str | None
    body: str
    available_modalities: tuple[ContentModality, ...]
    comprehension_checkpoints: tuple[dict[str, object], ...] = ()
    text_variant: dict[str, object] | None = None
    visual_variant: dict[str, object] | None = None
    audio_variant: dict[str, object] | None = None
    interactive_variant: dict[str, object] | None = None
    calculation_variant: dict[str, object] | None = None
    needs_review: bool = False
    review_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ParsedLesson:
    title: str
    segments: tuple[ParsedLessonSegment, ...]
    review_notes: tuple[dict[str, object], ...] = ()
    confirmation_summary: str | None = None
    gemini_call_count: int = 0
    chunk_count: int = 1


@dataclass(frozen=True, slots=True)
class StoredParsedLesson:
    lesson_id: UUID
    parse_run_id: UUID
    status: ContentParseStatus
    title: str
    segment_count: int
    review_segment_count: int
    confirmation_summary: str | None
    review_notes: tuple[dict[str, object], ...]
    segments: tuple[ParsedLessonSegment, ...]
