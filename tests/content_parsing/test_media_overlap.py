"""Pictures and audio are made at the same time, each under its own limit."""

import asyncio
import time
from uuid import uuid4

from nevo.audio.service import AudioGenerationError
from nevo.content_parsing.entities import ContentParseRequest, ParsedLessonSegment
from nevo.content_parsing.service import (
    AUDIO_CONCURRENCY,
    VISUAL_CONCURRENCY,
    ContentParsingService,
)
from nevo.domain.intelligence.vocabulary import (
    ContentModality,
    LessonContentType,
    LessonSourceType,
)
from nevo.visuals import VisualGenerationError

from .test_service import FakeGateway, FakeRepository


class Tracker:
    """Records when each call starts and ends, and how many ran at once."""

    def __init__(self, delay: float = 0.02) -> None:
        self.delay = delay
        self.in_flight = 0
        self.peak = 0
        self.spans: list[tuple[float, float]] = []

    async def track(self) -> None:
        started = time.perf_counter()
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
        finally:
            self.in_flight -= 1
            self.spans.append((started, time.perf_counter()))


class FakeAudio(Tracker):
    configured = True

    def __init__(self, *, fail_on: str | None = None, delay: float = 0.02) -> None:
        super().__init__(delay)
        self.fail_on = fail_on

    async def generate(self, script: str) -> dict[str, object]:
        await self.track()
        if self.fail_on is not None and self.fail_on in script:
            raise AudioGenerationError("YarnGPT generation failed with status 500")
        return {"script": script, "audioUrl": f"https://audio.example/{abs(hash(script))}.mp3"}


class FakeVisuals(Tracker):
    configured = True

    def __init__(self, *, fail_on: str | None = None, delay: float = 0.02) -> None:
        super().__init__(delay)
        self.fail_on = fail_on

    async def generate(self, *, title, lesson_text, requested_prompt=None):  # type: ignore[no-untyped-def]
        await self.track()
        if self.fail_on is not None and self.fail_on in lesson_text:
            raise VisualGenerationError("OpenAI answered 429")
        return {
            "type": "ai_generated_image",
            "imageUrl": f"https://image.example/{title}.png",
            "prompt": lesson_text,
            "provider": "openai",
            "generatedAt": "2026-09-21T09:00:00Z",
        }


def segment(
    key: str,
    *,
    steps: int = 0,
    needs_review: bool = False,
    reasons: tuple[str, ...] = (),
) -> ParsedLessonSegment:
    calculation = None
    if steps:
        calculation = {
            "steps": [
                {
                    "stepId": f"{key}-step-{n}",
                    "prompt": f"{key} step {n}",
                    "narrationAudio": {"script": f"{key} narration {n}"},
                }
                for n in range(steps)
            ]
        }
    return ParsedLessonSegment(
        segment_key=key,
        content_type=LessonContentType.EXPLANATORY_TEXT,
        sequence_order=1,
        title=key,
        body=f"Body of {key}",
        available_modalities=(ContentModality.TEXT, ContentModality.VISUAL, ContentModality.AUDIO),
        audio_variant={"script": f"Script of {key}"},
        calculation_variant=calculation,
        needs_review=needs_review,
        review_reasons=reasons,
    )


def service_with(audio: FakeAudio | None, visuals: FakeVisuals | None) -> ContentParsingService:
    return ContentParsingService(
        repository=FakeRepository(),  # type: ignore[arg-type]
        ai_gateway=FakeGateway(""),  # type: ignore[arg-type]
        audio_generation=audio,  # type: ignore[arg-type]
        visual_generation=visuals,  # type: ignore[arg-type]
    )


def overlaps(first: list[tuple[float, float]], second: list[tuple[float, float]]) -> bool:
    return any(
        a_start < b_end and b_start < a_end for a_start, a_end in first for b_start, b_end in second
    )


async def test_audio_and_pictures_are_made_at_the_same_time() -> None:
    audio, visuals = FakeAudio(delay=0.05), FakeVisuals(delay=0.05)
    service = service_with(audio, visuals)
    segments = [segment("a"), segment("b")]

    started = time.perf_counter()
    await service._generate_media(segments, [])
    elapsed = time.perf_counter() - started

    assert overlaps(audio.spans, visuals.spans)
    # One after the other would take both delays back to back.
    assert elapsed < 0.09


async def test_a_segment_keeps_its_picture_its_audio_and_every_review_reason() -> None:
    audio, visuals = FakeAudio(fail_on="Script of b"), FakeVisuals(fail_on="Body of c")
    service = service_with(audio, visuals)
    segments = [
        segment("a", steps=2),
        segment("b", reasons=("model_flagged_for_review",), needs_review=True),
        segment("c"),
    ]
    notes: list[dict[str, object]] = []

    merged = await service._generate_media(segments, notes)

    a, b, c = merged
    assert [m.segment_key for m in merged] == ["a", "b", "c"]
    # Everything the two passes made on "a" is there.
    assert a.visual_variant is not None
    assert a.audio_variant is not None
    assert a.audio_variant["audioUrl"].startswith("https://audio.example/")
    assert a.calculation_variant is not None
    assert all(
        step["narrationAudio"]["audioUrl"].startswith("https://audio.example/")
        for step in a.calculation_variant["steps"]
    )
    assert not a.needs_review
    # "b" lost its audio, kept its picture, and kept the reason it came in with.
    assert b.visual_variant is not None
    assert b.audio_variant == {"script": "Script of b"}
    assert b.review_reasons == ("model_flagged_for_review", "audio_generation_failed")
    assert b.needs_review
    # "c" lost its picture, kept its audio.
    assert c.visual_variant is None
    assert c.audio_variant is not None
    assert c.review_reasons == ("visual_generation_failed",)
    assert c.needs_review


async def test_both_passes_failing_on_one_segment_keeps_both_reasons_once() -> None:
    audio, visuals = FakeAudio(fail_on="Script of a"), FakeVisuals(fail_on="Body of a")
    service = service_with(audio, visuals)

    [merged] = await service._generate_media(
        [segment("a", reasons=("visual_generation_failed",))], []
    )

    assert merged.review_reasons == ("visual_generation_failed", "audio_generation_failed")
    assert merged.needs_review


async def test_only_one_provider_configured_leaves_the_other_fields_alone() -> None:
    original = segment("a", steps=1)

    [only_audio] = await service_with(FakeAudio(), None)._generate_media([original], [])
    [only_visual] = await service_with(None, FakeVisuals())._generate_media([original], [])
    [neither] = await service_with(None, None)._generate_media([original], [])

    assert only_audio.visual_variant is None and only_audio.audio_variant is not None
    assert only_visual.visual_variant is not None and only_visual.audio_variant == {
        "script": "Script of a"
    }
    assert only_visual.calculation_variant == original.calculation_variant
    assert neither == original


async def test_audio_never_runs_more_than_its_limit_and_pictures_more_than_theirs() -> None:
    audio, visuals = FakeAudio(), FakeVisuals()
    service = service_with(audio, visuals)
    # Twelve segments and six narrated steps each: far more clips than the limit.
    segments = [segment(f"s{n}", steps=6) for n in range(12)]

    await service._generate_media(segments, [])

    assert AUDIO_CONCURRENCY == 4
    assert VISUAL_CONCURRENCY == 2
    assert audio.peak == AUDIO_CONCURRENCY
    assert visuals.peak == VISUAL_CONCURRENCY
    assert len(audio.spans) == 12 * 7
    assert len(visuals.spans) == 12


async def test_one_segments_calculation_narrations_are_made_together() -> None:
    audio = FakeAudio()
    service = service_with(audio, None)

    await service._generate_media([segment("a", steps=3)], [])

    # Its own audio and three narrations queue for four places, so all four
    # overlap. Sequential narration would peak at two.
    assert audio.peak == 4


async def test_a_failed_narration_flags_only_that_segment() -> None:
    audio = FakeAudio(fail_on="b narration 1")
    service = service_with(audio, None)
    segments = [segment("a", steps=2), segment("b", steps=2)]

    a, b = await service._generate_media(segments, [])

    assert not a.needs_review
    assert b.review_reasons == ("calculation_audio_generation_failed",)
    assert b.calculation_variant is not None
    steps = b.calculation_variant["steps"]
    assert steps[0]["narrationAudio"]["audioUrl"].startswith("https://audio.example/")
    assert steps[1]["narrationAudio"] == {"script": "b narration 1"}


async def test_every_note_names_its_segment_and_its_kind() -> None:
    audio, visuals = FakeAudio(fail_on="Script"), FakeVisuals(fail_on="Body")
    service = service_with(audio, visuals)
    segments = [segment("a"), segment("b"), segment("c")]
    notes: list[dict[str, object]] = []

    await service._generate_media(segments, notes)

    assert len(notes) == 6
    assert {(note["segment"], note["code"]) for note in notes} == {
        (key, code)
        for key in ("a", "b", "c")
        for code in ("audio_generation_failed", "visual_generation_failed")
    }


async def test_a_full_parse_reports_a_failed_segment_in_the_lesson_notes() -> None:
    repository = FakeRepository()
    gateway = FakeGateway(
        """
        {"segments": [
          {"segment_key": "one", "content_type": "explanatory_text",
           "body": "First idea.", "availableModalities": ["text", "audio", "visual"]},
          {"segment_key": "two", "content_type": "explanatory_text",
           "body": "Second idea.", "availableModalities": ["text", "audio", "visual"]}
        ]}
        """
    )
    service = ContentParsingService(
        repository=repository,  # type: ignore[arg-type]
        ai_gateway=gateway,  # type: ignore[arg-type]
        audio_generation=FakeAudio(fail_on="Second"),  # type: ignore[arg-type]
        visual_generation=FakeVisuals(fail_on="Second"),  # type: ignore[arg-type]
    )

    await service.parse(
        request=ContentParseRequest(
            title="Ideas", source_type=LessonSourceType.TEXT, source_text="First. Second."
        ),
        requested_by_user_id=uuid4(),
    )

    first, second = repository.parsed.segments  # type: ignore[union-attr]
    assert not first.needs_review
    assert first.visual_variant is not None
    assert first.audio_variant is not None
    assert second.needs_review
    assert {"audio_generation_failed", "visual_generation_failed"} <= set(second.review_reasons)
    coded = [
        (note["segment"], note["code"])
        for note in repository.parsed.review_notes  # type: ignore[union-attr]
        if "segment" in note
    ]
    assert coded == [("two", "audio_generation_failed"), ("two", "visual_generation_failed")]
