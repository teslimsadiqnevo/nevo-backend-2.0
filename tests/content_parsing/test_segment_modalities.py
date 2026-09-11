"""What a segment offers by the time it reaches the database.

``lesson_segments`` carries a check constraint refusing a row with no
modalities at all. Nothing upstream enforced that, so one segment offering
nothing failed the insert and took every other segment in the lesson with it:
the parse reported `failed`, `segmentCount: 0`, and a teacher's upload was
gone.
"""

from __future__ import annotations

from nevo.content_parsing.entities import ParsedLessonSegment
from nevo.content_parsing.service import _normalize_segment
from nevo.domain.intelligence.vocabulary import (
    ContentModality,
    LessonContentType,
    SegmentReviewReason,
)

AUDIO = {"audioUrl": "https://cdn.example/narration.mp3", "voice": "Idera"}
IMAGE = {
    "type": "ai_generated_image",
    "imageUrl": "https://cdn.example/bands.png",
    "prompt": "three equal bands",
    "provider": "openai",
    "generatedAt": "2026-09-11T20:39:48Z",
}
STEPS = {
    "type": "co_construction",
    "fullEquation": "I = (20000 × 5 × 3) ÷ 100",  # noqa: RUF001
    "answer": "3000",
    "steps": [
        {"stepId": "step-1", "prompt": "Multiply", "expectedInput": "numeric"},
        {"stepId": "step-2", "prompt": "Divide", "expectedInput": "numeric"},
    ],
}


def _calculation(**overrides: object) -> ParsedLessonSegment:
    fields: dict[str, object] = {
        "segment_key": "segment-4",
        "content_type": LessonContentType.CALCULATION,
        "sequence_order": 4,
        "title": "Calculating Simple Interest: Co-construction",
        "body": "You will now work through the steps to calculate simple interest.",
        "available_modalities": (ContentModality.INTERACTIVE, ContentModality.VISUAL),
        "text_variant": {"body": "You will now work through the steps."},
        "audio_variant": AUDIO,
        "calculation_variant": STEPS,
    }
    fields.update(overrides)
    return ParsedLessonSegment(**fields)  # type: ignore[arg-type]


def test_a_calculation_with_neither_delivery_still_offers_something() -> None:
    # The exact row that failed in production: the co-construction was
    # rejected as malformed and the image provider was out of credit.
    segment = _normalize_segment(_calculation(calculation_variant=None))
    assert segment.available_modalities
    assert ContentModality.TEXT in segment.available_modalities
    assert ContentModality.AUDIO in segment.available_modalities
    assert segment.needs_review
    assert (
        SegmentReviewReason.CALCULATION_SEGMENT_HAS_NO_INTERACTIVE_DELIVERY
        in segment.review_reasons
    )


def test_it_does_not_promise_audio_that_was_never_made() -> None:
    segment = _normalize_segment(_calculation(calculation_variant=None, audio_variant=None))
    assert segment.available_modalities == (ContentModality.TEXT,)


def test_a_working_co_construction_is_still_interactive() -> None:
    # The fallback must not fire when the segment has what it should have.
    segment = _normalize_segment(_calculation())
    assert ContentModality.INTERACTIVE in segment.available_modalities
    assert (
        SegmentReviewReason.CALCULATION_SEGMENT_HAS_NO_INTERACTIVE_DELIVERY
        not in segment.review_reasons
    )


def test_a_picture_alone_is_enough_to_keep_the_segment_visual() -> None:
    segment = _normalize_segment(_calculation(calculation_variant=None, visual_variant=IMAGE))
    assert ContentModality.VISUAL in segment.available_modalities


def test_every_content_type_ends_up_with_a_modality() -> None:
    # The database constraint applies to every row, not only calculation.
    for content_type in LessonContentType:
        segment = _normalize_segment(
            ParsedLessonSegment(
                segment_key="segment-1",
                content_type=content_type,
                sequence_order=1,
                title=None,
                body="Interest is what a bank pays you for leaving money there.",
                available_modalities=(),
            )
        )
        assert segment.available_modalities, content_type
