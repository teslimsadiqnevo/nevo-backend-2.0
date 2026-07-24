from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from nevo.api.auth import PrincipalDependency
from nevo.content_parsing.entities import (
    ContentParseRequest,
    ParsedLessonSegment,
    SourcePage,
    StoredParsedLesson,
)
from nevo.content_parsing.service import ContentParsingService
from nevo.domain.intelligence.vocabulary import (
    ContentModality,
    ContentParseStatus,
    LessonContentType,
    LessonSourceType,
)

router = APIRouter(prefix="/api/content", tags=["content"])


class SourcePageRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    page_number: int = Field(alias="pageNumber", ge=1)
    text: str = Field(min_length=1)


class ParseContentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str = Field(min_length=1, max_length=255)
    source_type: LessonSourceType = Field(alias="sourceType")
    source_text: str | None = Field(default=None, alias="sourceText")
    pages: list[SourcePageRequest] = Field(default_factory=list, max_length=2_000)
    source_metadata: dict[str, object] = Field(
        default_factory=dict,
        alias="sourceMetadata",
    )

    @model_validator(mode="after")
    def require_source_material(self) -> "ParseContentRequest":
        if self.source_text and self.source_text.strip():
            return self
        if self.pages:
            return self
        if self.source_metadata.get("importReference"):
            return self
        raise ValueError(
            "sourceText, pages, or sourceMetadata.importReference is required"
        )


class ParsedLessonSegmentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    content_type: LessonContentType = Field(alias="contentType")
    sequence_order: int = Field(alias="sequenceOrder")
    title: str | None
    body: str
    available_modalities: list[ContentModality] = Field(alias="availableModalities")
    comprehension_checkpoints: list[dict[str, object]] = Field(
        alias="comprehensionCheckpoints"
    )
    text_variant: dict[str, object] | None = Field(alias="textVariant")
    visual_variant: dict[str, object] | None = Field(alias="visualVariant")
    audio_variant: dict[str, object] | None = Field(alias="audioVariant")
    interactive_variant: dict[str, object] | None = Field(alias="interactiveVariant")
    calculation_variant: dict[str, object] | None = Field(alias="calculationVariant")
    needs_review: bool = Field(alias="needsReview")
    review_reasons: list[str] = Field(alias="reviewReasons")

    @classmethod
    def from_segment(
        cls,
        segment: ParsedLessonSegment,
    ) -> "ParsedLessonSegmentResponse":
        return cls(
            id=segment.segment_key,
            content_type=segment.content_type,
            sequence_order=segment.sequence_order,
            title=segment.title,
            body=segment.body,
            available_modalities=list(segment.available_modalities),
            comprehension_checkpoints=list(segment.comprehension_checkpoints),
            text_variant=segment.text_variant,
            visual_variant=segment.visual_variant,
            audio_variant=segment.audio_variant,
            interactive_variant=segment.interactive_variant,
            calculation_variant=segment.calculation_variant,
            needs_review=segment.needs_review,
            review_reasons=list(segment.review_reasons),
        )


class ParseContentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    lesson_id: UUID = Field(alias="lessonId")
    parse_run_id: UUID = Field(alias="parseRunId")
    status: ContentParseStatus
    title: str
    segment_count: int = Field(alias="segmentCount")
    review_segment_count: int = Field(alias="reviewSegmentCount")
    confirmation_summary: str | None = Field(alias="confirmationSummary")
    review_notes: list[dict[str, object]] = Field(alias="reviewNotes")
    segments: list[ParsedLessonSegmentResponse]

    @classmethod
    def from_result(cls, result: StoredParsedLesson) -> "ParseContentResponse":
        return cls(
            lesson_id=result.lesson_id,
            parse_run_id=result.parse_run_id,
            status=result.status,
            title=result.title,
            segment_count=result.segment_count,
            review_segment_count=result.review_segment_count,
            confirmation_summary=result.confirmation_summary,
            review_notes=list(result.review_notes),
            segments=[
                ParsedLessonSegmentResponse.from_segment(segment)
                for segment in result.segments
            ],
        )


def get_content_parsing_service(request: Request) -> ContentParsingService:
    service = getattr(request.app.state, "content_parsing_service", None)
    if not isinstance(service, ContentParsingService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_unavailable",
                "message": "Content parsing is temporarily unavailable.",
            },
        )
    return service


ContentParsingDependency = Annotated[
    ContentParsingService,
    Depends(get_content_parsing_service),
]


@router.post("/parse", response_model=ParseContentResponse)
async def parse_content(
    payload: ParseContentRequest,
    principal: PrincipalDependency,
    service: ContentParsingDependency,
) -> ParseContentResponse:
    result = await service.parse(
        request=ContentParseRequest(
            title=payload.title,
            source_type=payload.source_type,
            source_text=payload.source_text,
            pages=tuple(
                SourcePage(page_number=page.page_number, text=page.text)
                for page in payload.pages
            ),
            source_metadata=payload.source_metadata,
        ),
        requested_by_user_id=principal.user_id,
    )
    return ParseContentResponse.from_result(result)
