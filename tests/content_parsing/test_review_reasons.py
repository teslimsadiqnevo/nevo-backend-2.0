"""Review reasons the console can actually render.

The parser is asked to flag segments for review, and answers in its own words.
One such sentence went into the column as written, and every read of that
lesson afterwards was a 500: the field is an enum, and no enum member is a
sentence about practice questions needing audio.
"""

from __future__ import annotations

from uuid import uuid4

from nevo.api.frontend_unblockers import LessonSegmentResponse as UnblockerSegment
from nevo.api.response_models import LessonSegmentResponse as SharedSegment
from nevo.content_parsing.service import _review_reasons
from nevo.domain.intelligence.vocabulary import LessonContentType, SegmentReviewReason

# What the model actually wrote, from the row that broke the live lesson.
PROSE = (
    "Practice questions lack interactive or audio modalities for all learners "
    "to access them. Teacher should consider providing audio versions of these "
    "problems or creating interactive versions using digital tools."
)


def test_prose_becomes_a_reason_the_console_can_name() -> None:
    assert _review_reasons([PROSE]) == [SegmentReviewReason.MODEL_FLAGGED_FOR_REVIEW.value]


def test_a_known_reason_is_kept_as_it_is() -> None:
    assert _review_reasons(["visual_generation_failed"]) == ["visual_generation_failed"]


def test_the_same_reason_is_not_repeated() -> None:
    # Two different sentences both mean "a human should look", and saying so
    # twice tells a teacher nothing extra.
    assert _review_reasons([PROSE, "Another thought entirely"]) == [
        SegmentReviewReason.MODEL_FLAGGED_FOR_REVIEW.value
    ]


def test_nothing_in_means_nothing_out() -> None:
    assert _review_reasons(None) == []
    assert _review_reasons([]) == []


def _segment_payload() -> dict[str, object]:
    return {
        "id": uuid4(),
        "segmentKey": "segment-8",
        "sequenceOrder": 8,
        "contentType": LessonContentType.PRACTICE_QUESTION,
        "title": "Practice questions",
        "body": "Find the simple interest on 8,000 naira at 4% per annum for 5 years.",
        "availableModalities": ["text", "visual"],
        "comprehensionCheckpoints": [],
        "needsReview": True,
        "reviewReasons": [PROSE, "visual_generation_failed"],
        "estimatedMinutes": 3,
    }


def test_a_stored_sentence_does_not_take_the_lesson_down_with_it() -> None:
    # Rows written before the parse filtered these are still in the database,
    # so reading has to survive them without a data migration.
    for model in (SharedSegment, UnblockerSegment):
        segment = model.model_validate(_segment_payload())
        assert segment.review_reasons == [SegmentReviewReason.VISUAL_GENERATION_FAILED], model
        assert segment.needs_review, model
