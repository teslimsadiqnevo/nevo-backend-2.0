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
            provider=AiProviderName.CLAUDE,
            model="claude-haiku-4-5",
            prompt_name=request.prompt_name,
            prompt_version=1,
            fallback_used=False,
            compliance_retries=0,
            call_id=uuid4(),
        )


class FakeRepository:
    def __init__(self) -> None:
        self.parsed: ParsedLesson | None = None

    async def store(
        self,
        *,
        request,
        parsed,
        requested_by_user_id,
        existing_lesson_id=None,
        parse_run_id=None,
    ):
        self.parsed = parsed
        return type(
            "Stored",
            (),
            {
                "lesson_id": uuid4(),
                "parse_run_id": uuid4(),
                "status": ContentParseStatus.COMPLETED_WITH_REVIEW
                if parsed.review_notes or any(segment.needs_review for segment in parsed.segments)
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


class FakeAudioGeneration:
    configured = True

    def __init__(self) -> None:
        self.scripts: list[str] = []

    async def generate(self, script: str) -> dict[str, object]:
        self.scripts.append(script)
        return {
            "script": script,
            "audioUrl": f"https://audio.example/{len(self.scripts)}.mp3",
            "storagePath": f"audio/{len(self.scripts)}.mp3",
            "durationMs": 0,
            "provider": "yarngpt",
            "voice": "Idera",
            "format": "mp3",
            "requiresAuthentication": False,
        }


@pytest.mark.asyncio
async def test_parses_ai_segments_and_normalizes_calculation_variant() -> None:
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
async def test_generates_segment_audio_when_configured() -> None:
    repository = FakeRepository()
    audio = FakeAudioGeneration()
    service = ContentParsingService(
        repository=repository,
        ai_gateway=FakeGateway(
            """
            {"segments": [{
              "segment_key": "audio-1",
              "content_type": "explanatory_text",
              "body": "Equivalent fractions have the same value.",
              "availableModalities": ["text", "audio"]
            }]}
            """
        ),
        audio_generation=audio,  # type: ignore[arg-type]
    )

    await service.parse(
        request=ContentParseRequest(
            title="Fractions",
            source_type=LessonSourceType.TEXT,
            source_text="Equivalent fractions have the same value.",
        ),
        requested_by_user_id=uuid4(),
    )

    segment = repository.parsed.segments[0]  # type: ignore[union-attr]
    assert segment.audio_variant is not None
    assert segment.audio_variant["provider"] == "yarngpt"
    assert segment.audio_variant["audioUrl"] == "https://audio.example/1.mp3"


@pytest.mark.asyncio
async def test_falls_back_to_reviewable_segments_when_ai_json_is_invalid() -> None:
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
    assert result.review_notes[0]["code"] == "ai_parse_fallback"
    assert repository.parsed.segments[0].available_modalities[0] is ContentModality.TEXT  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_visual_modality_is_removed_when_generated_image_is_missing() -> None:
    repository = FakeRepository()
    service = ContentParsingService(
        repository=repository,
        ai_gateway=FakeGateway(
            """
            {
              "segments": [
                {
                  "segment_key": "visual-1",
                  "content_type": "explanatory_text",
                  "body": "A numerator shows selected equal parts.",
                  "availableModalities": ["text", "visual", "audio"],
                  "visual_variant": {
                    "type": "ai_generated_image",
                    "prompt": "Equal parts diagram",
                    "provider": "image-provider",
                    "generatedAt": "2026-08-22T10:00:00Z"
                  }
                }
              ]
            }
            """
        ),
    )

    result = await service.parse(
        request=ContentParseRequest(
            title="Fractions",
            source_type=LessonSourceType.TEXT,
            source_text="A numerator shows selected equal parts.",
        ),
        requested_by_user_id=uuid4(),
    )

    segment = repository.parsed.segments[0]  # type: ignore[union-attr]
    assert result.status is ContentParseStatus.COMPLETED_WITH_REVIEW
    assert ContentModality.VISUAL not in segment.available_modalities
    assert segment.visual_variant is None
    assert "visual_variant_image_generation_failed" in segment.review_reasons


def test_truncated_json_is_reported_as_truncated_not_just_invalid() -> None:
    """More tokens and a better prompt are different fixes; the exception
    class alone cannot tell them apart."""
    from nevo.content_parsing.service import _looks_truncated

    class Result:
        def __init__(self, text: str) -> None:
            self.text = text

    assert _looks_truncated(Result('{"segments": [{"title": "A"'))
    assert not _looks_truncated(Result('{"segments": []}'))
    assert not _looks_truncated(Result("not json at all"))
    assert not _looks_truncated(None)


def test_the_parse_asks_for_enough_room_to_answer() -> None:
    """At 4,096 the model ran out mid-object and every lesson silently fell
    back to deterministic text."""
    from nevo.content_parsing.service import PARSE_OUTPUT_TOKENS

    assert PARSE_OUTPUT_TOKENS >= 16_000


def test_a_lesson_parse_asks_for_the_time_it_needs() -> None:
    """Raising the token budget without the timeout only moved the failure:
    the model was still writing when the shared 20s ceiling cut it off."""
    from nevo.content_parsing.service import PARSE_TIMEOUT_SECONDS

    assert PARSE_TIMEOUT_SECONDS >= 120


async def test_media_generation_runs_a_few_at_a_time_not_all_at_once() -> None:
    """Unbounded lost media to provider rate limits; sequential was slow."""
    import asyncio

    from nevo.content_parsing.service import GENERATION_CONCURRENCY, _in_parallel

    in_flight = 0
    peak = 0

    async def step(segment):  # type: ignore[no-untyped-def]
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return segment

    segments = [object() for _ in range(8)]

    result = await _in_parallel(step, segments)  # type: ignore[arg-type]

    assert len(result) == 8
    assert peak <= GENERATION_CONCURRENCY
    assert GENERATION_CONCURRENCY > 1


async def test_a_lost_picture_says_why_in_the_run_notes() -> None:
    """"visual_generation_failed" on its own told nobody anything, which is
    how every image in a lesson went missing for two days."""
    from nevo.visuals import VisualGenerationError

    class FailingVisuals:
        configured = True

        async def generate(self, **kwargs):  # type: ignore[no-untyped-def]
            raise VisualGenerationError("Image generation exceeded its time budget")

    repository = FakeRepository()
    service = ContentParsingService(
        repository=repository,
        ai_gateway=FakeGateway(
            """
            {
              "segments": [
                {
                  "segment_key": "visual-1",
                  "content_type": "explanatory_text",
                  "body": "A numerator shows selected equal parts.",
                  "availableModalities": ["text", "visual"]
                }
              ]
            }
            """
        ),
        visual_generation=FailingVisuals(),  # type: ignore[arg-type]
    )

    await service.parse(
        request=ContentParseRequest(
            title="Fractions",
            source_type=LessonSourceType.TEXT,
            source_text="Fractions are parts of a whole.",
        ),
        requested_by_user_id=uuid4(),
    )
    notes = [
        note
        for note in repository.parsed.review_notes
        if note.get("code") == "visual_generation_failed"
    ]

    assert notes
    assert "time budget" in str(notes[0]["reason"])
    assert "secondsSpent" in notes[0]


def test_the_image_budget_is_not_the_thing_that_fails_a_lesson() -> None:
    """210 seconds was under what a high-quality image plus its review takes."""
    from nevo.visuals.config import VisualGenerationSettings

    assert VisualGenerationSettings().budget_seconds >= 600
