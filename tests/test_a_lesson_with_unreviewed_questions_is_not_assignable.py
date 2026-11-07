"""A half-reviewed lesson is refused, not delivered with gaps.

Lydia's ruling of 7 November. Unreviewed questions were already held back
from delivery, which was right, but the lesson was still assignable in that
state - so the rule produced a half-delivered lesson instead of preventing
a premature one.

ready_to_assign required the key points, the rewrites and the guided steps
to be signed off, and not the checks or the calculation parts. So a lesson
whose questions nobody had approved could be put in front of a class, and
the child simply met fewer questions than the teacher thought they had set.

The refusal also has to name the step. A teacher told only that they cannot
assign does not know whether it is pictures, checks or rewrites.
"""

from __future__ import annotations

import inspect

from nevo.api import frontend_unblockers, lesson_review, product_common, product_learning
from nevo.main import app

SPEC = app.openapi()


def test_every_review_step_gates_assignment() -> None:
    source = inspect.getsource(lesson_review._review_result)
    # All five, not the three it used to be.
    for step in (
        "key_points",
        "rewrites",
        "guided_steps",
        "checks",
        "calculation_parts",
    ):
        assert f'"{step}"' in source, step
    assert '"ready_to_assign": not outstanding_steps' in source


def test_a_step_with_nothing_in_it_does_not_block() -> None:
    # A lesson with no calculations cannot have its calculation parts
    # approved, so requiring that sign-off would make it unassignable for
    # ever. Key points are required either way.
    source = inspect.getsource(lesson_review._review_result)
    assert '"key_points": True' in source
    assert '"calculation_parts": bool(calculation_material)' in source


def test_the_outstanding_steps_are_published() -> None:
    properties = SPEC["components"]["schemas"]["LessonReviewResponse"]["properties"]
    assert "outstandingReviewSteps" in properties


def test_the_refusal_names_the_step() -> None:
    source = inspect.getsource(product_common)
    assert "outstandingReviewSteps" in source
    assert "steps=steps_left.get(lesson_id, [])" in source
    # In the words the screen uses, not the stored keys.
    assert product_common.REVIEW_STEP_NAMES["media"] == "pictures"
    assert product_common.REVIEW_STEP_NAMES["calculation_parts"] == "calculation parts"


def test_the_phrase_says_something_even_with_no_counts() -> None:
    # A lesson blocked only by an unsigned step has no outstanding key points
    # and no unapproved segments, so the message used to come out as the
    # title and a colon.
    phrase = product_common._outstanding_phrase(
        "Fractions", segments=0, key_points=0, steps=["checks"]
    )
    assert "checks still to sign off" in phrase
    assert phrase.startswith("Fractions:")

    bare = product_common._outstanding_phrase("Fractions", segments=0, key_points=0, steps=[])
    assert bare.strip() != "Fractions:"


def test_the_steps_read_in_the_order_the_review_presents_them() -> None:
    phrase = product_common._outstanding_phrase(
        "Fractions", segments=0, key_points=0, steps=["checks", "calculation parts"]
    )
    assert phrase.index("checks") < phrase.index("calculation parts")


def test_there_is_no_way_to_ask_for_assignability_without_checks() -> None:
    # review_complete_map took require_checks, and both library listings
    # passed it False so that can_assign could be true while the questions
    # were unreviewed. That is the half-delivered lesson, computed on
    # purpose. The parameter is gone, so it cannot come back by default.
    assert "require_checks" not in inspect.signature(lesson_review.review_complete_map).parameters
    for module in (product_learning, frontend_unblockers):
        assert "require_checks=" not in inspect.getsource(module)


def test_the_library_flag_and_the_assignment_gate_agree() -> None:
    # Two reads of the same question. A library that offers a lesson as
    # assignable and an assignment that refuses it is worse than either.
    for module in (product_learning, frontend_unblockers):
        source = inspect.getsource(module)
        assert "assignable = review_complete" in source or "assignable = complete" in source


def test_calculation_parts_gate_the_library_too() -> None:
    source = inspect.getsource(lesson_review.review_complete_map)
    assert '"calculation_parts": calculation' in source
