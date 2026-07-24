from uuid import uuid4

import pytest

from nevo.ai_gateway.entities import AiGenerationResult
from nevo.content_parsing.entities import ContentParseRequest, ParsedLesson
from nevo.content_parsing.service import ContentParsingService
from nevo.domain.ai_gateway.vocabulary import AiProviderName
from nevo.domain.intelligence.vocabulary import (
    ContentModality,
    ContentParseStatus,
    LessonContentType,
    LessonSourceType,
)


class FakeGateway:
    def __init__(self, text: str) -> None:
        self.text = text
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        return AiGenerationResult(
            text=self.text,
            provider=AiProviderName.GEMINI,
            model="test",
            prompt_name=request.prompt_name,
            prompt_version=1,
            fallback_used=False,
            compliance_retries=0,
            call_id=uuid4(),
        )


class FakeRepository:
    def __init__(self) -> None:
        self.parsed: ParsedLesson | None = None

    async def store(self, *, request, parsed, requested_by_user_id):
        self.parsed = parsed
        return type(
            "Stored",
            (),
            {
                "lesson_id": uuid4(),
                "parse_run_id": uuid4(),
                "status": ContentParseStatus.COMPLETED_WITH_REVIEW
                if parsed.review_notes
                or any(segment.needs_review for segment in parsed.segments)
                else ContentParseStatus.COMPLETED,
                "title": parsed.title,
                "segment_count": len(parsed.segments),
                "review_segment_count": sum(
                    1 for segment in parsed.segments if segment.needs_review
                ),
                "confirmation_summary": parsed.confirmation_summary,
                "review_notes": parsed.review_notes,
                "segments": parsed.segments,
            },
        )()


@pytest.mark.asyncio
async def test_parses_gemini_segments_and_normalizes_calculation_variant() -> None:
    repository = FakeRepository()
    gateway = FakeGateway(
        """
        {
          "segments": [
            {
              "segment_key": "calc-1",
              "content_type": "calculation",
              "sequence_order": 1,
              "title": "Add fractions",
              "body": "1/2 + 1/4",
              "availableModalities": ["text", "audio"],
              "calculation_variant": {
                "fullEquation": "1/2 + 1/4",
                "steps": [
                  {
                    "stepId": "s1",
                    "prompt": "What common denominator can we use?",
                    "expectedInput": "numeric",
                    "hint": "Look for a shared multiple.",
                    "confirmationText": "Yes, fourths work.",
                    "visualUpdate": "Highlight denominators.",
                    "equationState": "1/2 + 1/4"
                  },
                  {
                    "stepId": "s2",
                    "prompt": "What is one half in fourths?",
                    "expectedInput": "numeric",
                    "hint": "Two fourths equal one half.",
                    "confirmationText": "Correct.",
                    "visualUpdate": "Show two shaded fourths.",
                    "equationState": "2/4 + 1/4"
                  }
                ],
                "completionStatement": "Three fourths."
              }
            }
          ]
        }
        """
    )
    service = ContentParsingService(repository=repository, ai_gateway=gateway)

    result = await service.parse(
        request=ContentParseRequest(
            title="Fractions",
            source_type=LessonSourceType.TEXT,
            source_text="Add 1/2 and 1/4.",
        ),
        requested_by_user_id=uuid4(),
    )

    assert result.status is ContentParseStatus.COMPLETED
    segment = repository.parsed.segments[0]  # type: ignore[union-attr]
    assert segment.content_type is LessonContentType.CALCULATION
    assert segment.available_modalities == (
        ContentModality.INTERACTIVE,
        ContentModality.VISUAL,
    )
    assert segment.calculation_variant is not None
    steps = segment.calculation_variant["steps"]
    assert steps[0]["narrationAudio"]["provider"] == "tts_provider_tbd"


@pytest.mark.asyncio
async def test_falls_back_to_reviewable_segments_when_gemini_json_is_invalid() -> None:
    repository = FakeRepository()
    service = ContentParsingService(
        repository=repository,
        ai_gateway=FakeGateway("not-json"),
    )

    result = await service.parse(
        request=ContentParseRequest(
            title="Photosynthesis",
            source_type=LessonSourceType.TEXT,
            source_text="Plants use sunlight.\n\nSummary: energy is stored.",
        ),
        requested_by_user_id=uuid4(),
    )

    assert result.status is ContentParseStatus.COMPLETED_WITH_REVIEW
    assert result.segment_count == 2
    assert result.review_segment_count == 2
    assert result.review_notes[0]["code"] == "gemini_parse_fallback"
    assert repository.parsed.segments[0].available_modalities[0] is ContentModality.TEXT  # type: ignore[union-attr]
