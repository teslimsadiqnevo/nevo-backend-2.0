"""A blocked Ask Nevo message says which of Lydia's two lines applies.

She has one line for a block that names someone and one for everything else.
The 403 carried only a code and a message, so the app could not tell them
apart and showed the general line for every block.

Two values, not the category list: the categories are our own vocabulary, they
change as the policy changes, and a teacher is never told which rule fired.
"""

from __future__ import annotations

import pytest

from nevo.ai_gateway.safety import SafetyBlocked, SafetyUnavailable
from nevo.api.ai_gateway import public_ai_error


def _detail(categories, audience="teacher", about="question") -> dict:
    error = SafetyBlocked(categories=tuple(categories), phase="input:ask_nevo.teacher")
    return public_ai_error(error, audience=audience, about=about).detail


@pytest.mark.parametrize(
    "categories",
    [("privacy_abuse",), ("privacy_abuse", "violence"), ("violence", "privacy_abuse")],
)
def test_a_block_that_names_someone_says_so(categories) -> None:
    assert _detail(categories)["reason"] == "names_person"


@pytest.mark.parametrize("categories", [("self_harm",), ("violence",), (), ("unknown_thing",)])
def test_every_other_block_says_other(categories) -> None:
    assert _detail(categories)["reason"] == "other"


def test_the_category_vocabulary_never_reaches_the_teacher() -> None:
    """She is told which line applies, never which rule fired."""
    detail = _detail(("privacy_abuse", "self_harm"))
    written = " ".join(str(value) for value in detail.values())
    for leak in ("privacy_abuse", "self_harm", "input:", "ask_nevo"):
        assert leak not in written, f"{leak} reached the teacher"


def test_a_child_is_not_sent_the_reason_at_all() -> None:
    """One line whatever the reason, so the shape of the refusal stays out."""
    detail = _detail(("privacy_abuse",), audience="learner")
    assert "reason" not in detail
    assert detail["message"].startswith("Nevo can")


def test_a_check_that_could_not_run_is_not_given_a_reason() -> None:
    """It is a different thing: try again shortly, rather than rephrase."""
    detail = public_ai_error(SafetyUnavailable("upstream"), audience="teacher").detail
    assert "reason" not in detail
    assert detail["code"] == "safety_check_unavailable"


def test_the_code_and_message_still_come_through() -> None:
    detail = _detail(("privacy_abuse",))
    assert detail["code"] == "content_safety_blocked"
    assert "held this question back" in detail["message"]


def test_a_lesson_block_keeps_its_own_wording_and_still_says_why() -> None:
    detail = _detail(("privacy_abuse",), about="lesson")
    assert "lesson content" in detail["message"]
    assert detail["reason"] == "names_person"
