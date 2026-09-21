"""A teacher can perform the review the product demands of them.

The lesson page said parts needed review and offered no way to review them, so
the lesson could never be assigned. These cover what the screen needs: which
points are outstanding, what Nevo read them from, and the three actions.
"""

from __future__ import annotations

import inspect

import pytest

from nevo.api.lesson_review import RESOLVED_STATES
from nevo.content_parsing.key_points import confidence, grounding
from nevo.db.models.content import LessonKeyPoint
from nevo.domain.intelligence.vocabulary import KeyPointConfidence, KeyPointReviewState
from nevo.main import app

REVIEW = "/api/v1/lessons/{lesson_id}/review"
POINT = "/api/v1/lessons/{lesson_id}/key-points/{key_point_id}"

SOURCE = (
    "Simple interest is found with I = (P x R x T) / 100, where P is the "
    "principal, R is the rate per annum and T is the time in years."
)


@pytest.fixture(scope="module")
def spec() -> dict:
    return app.openapi()


def test_a_point_lifted_from_the_source_is_not_put_to_a_teacher() -> None:
    point = "The rate R is the rate per annum"

    assert grounding(point, SOURCE) == 1.0
    assert confidence(point, SOURCE) is KeyPointConfidence.HIGH


def test_a_point_the_source_does_not_support_is_low_confidence() -> None:
    # Nothing here about compounding, houses or mortgages. This is exactly the
    # card a teacher should be asked to open.
    point = "Compound interest on a mortgage grows faster every year"

    assert confidence(point, SOURCE) is KeyPointConfidence.LOW


def test_a_point_of_nothing_but_filler_is_not_treated_as_grounded() -> None:
    assert grounding("It is what it is", SOURCE) == 0.0


def test_grounding_ignores_case_and_punctuation() -> None:
    assert grounding("PRINCIPAL, RATE, TIME.", SOURCE) == 1.0


def test_the_review_screen_has_a_read(spec: dict) -> None:
    assert "get" in spec["paths"][REVIEW]


def test_a_card_can_be_accepted_amended_or_removed(spec: dict) -> None:
    assert "post" in spec["paths"][POINT + "/accept"]
    assert {"patch", "delete"} <= set(spec["paths"][POINT])


def test_the_card_carries_what_the_expanded_state_renders(spec: dict) -> None:
    fields = spec["components"]["schemas"]["KeyPointResponse"]["properties"]

    # LR-02: the source text, what Nevo read, and how sure it was.
    assert {"sourceText", "extractedText", "confidence", "outstanding"} <= set(fields)


def test_the_review_counts_down_and_says_when_assign_unlocks(spec: dict) -> None:
    fields = spec["components"]["schemas"]["LessonReviewResponse"]["properties"]

    # LR-04 shows a live count; LR-05 flips the lesson to ready.
    assert {"outstandingCount", "readyToAssign"} <= set(fields)


def test_only_an_unsure_point_blocks_assignment() -> None:
    # The ruling: a teacher never clicks through a lesson Nevo was sure of.
    assert KeyPointReviewState.SETTLED not in RESOLVED_STATES
    assert RESOLVED_STATES == {
        KeyPointReviewState.ACCEPTED,
        KeyPointReviewState.AMENDED,
        KeyPointReviewState.REMOVED,
    }


def test_a_teachers_wording_does_not_overwrite_what_nevo_read() -> None:
    columns = {column.name for column in LessonKeyPoint.__table__.columns}

    assert {"extracted_text", "amended_text", "source_text"} <= columns


def test_the_lesson_shows_the_teachers_wording_once_they_write_one() -> None:
    point = LessonKeyPoint(extracted_text="What Nevo read", amended_text=None)
    assert point.text == "What Nevo read"

    point.amended_text = "What the teacher meant"
    assert point.text == "What the teacher meant"


def test_the_gate_and_the_screen_count_the_same_thing() -> None:
    # Client and server disagreeing about "ready" is how the blocker started,
    # so the gate asks the same function the review screen is built from.
    from nevo.api.product_common import require_approved_lessons

    source = inspect.getsource(require_approved_lessons)

    assert "outstanding_key_points" in source


def test_the_gate_no_longer_taxes_a_lesson_nobody_doubted() -> None:
    from nevo.api.product_common import require_approved_lessons

    source = inspect.getsource(require_approved_lessons)

    assert "needs_review.is_(True)" in source
