"""A child is told which items they may work on paper, online and offline.

T6. The flag is derived from exactly the conditions the typed paper-work
route enforces - the check is approved, it has guided steps, those steps are
approved, and every one of them can be marked. Derived rather than stored,
because a stored copy drifts, and the failure that matters is the field
saying yes where the route says no: the child does the working and is then
refused.

The offline half is the point of the ask. A child working offline is the one
most likely to be working on paper, so an instruction that only appeared
online would be missing exactly when it matters.
"""

from __future__ import annotations

import inspect

from nevo.api import lesson_contracts
from nevo.api.lesson_contracts import (
    ComprehensionCheckpoint,
    PaperWorkOffer,
    paper_work_offer,
)


def _question(**overrides) -> ComprehensionCheckpoint:
    payload = {
        "id": "q1",
        "prompt": "Work it out",
        "answerType": "numeric",
        "answerKey": 12,
        "guidedSteps": [
            {"id": "s1", "prompt": "One", "answerType": "numeric", "answerKey": 4}
        ],
        "guidedStepsReviewStatus": "approved",
    }
    payload.update(overrides)
    return ComprehensionCheckpoint.model_validate(payload)


def test_an_approved_markable_check_may_be_worked_on_paper() -> None:
    offer = paper_work_offer(_question(), teacher_reviewed=True)
    assert offer["allowed"] is True
    assert offer["instruction"]
    assert offer["unavailableReason"] is None


def test_an_unapproved_check_is_not_offered() -> None:
    offer = paper_work_offer(_question(), teacher_reviewed=False)
    assert offer["allowed"] is False
    assert offer["instruction"] is None
    assert offer["unavailableReason"] == "check_not_approved"


def test_steps_still_in_review_are_not_offered() -> None:
    offer = paper_work_offer(
        _question(guidedStepsReviewStatus="pending_review"), teacher_reviewed=True
    )
    assert offer["allowed"] is False
    assert offer["unavailableReason"] == "steps_not_approved"


def test_a_question_with_no_steps_is_not_offered() -> None:
    offer = paper_work_offer(_question(guidedSteps=[]), teacher_reviewed=True)
    assert offer["allowed"] is False
    assert offer["unavailableReason"] == "no_steps"


def test_the_offer_matches_what_the_route_will_accept() -> None:
    """The conditions must be the same four, named in both places.

    If these drift, a child does the working and is then refused - the one
    outcome worth engineering against.
    """
    route = inspect.getsource(
        __import__("nevo.api.paper_work", fromlist=["submit_typed_paper_work"]).submit_typed_paper_work
    )
    assert "paper_work_steps_not_approved" in route
    assert "paper_work_steps_unmarkable" in route
    offer = inspect.getsource(paper_work_offer)
    assert "guided_steps_review_status" in offer
    assert "answer_key is not None" in offer
    assert "teacher_reviewed" in offer


def test_the_offer_is_declared_so_it_is_not_stripped() -> None:
    """includedSegmentIds was computed for weeks and never reached the app
    because it was not declared. Not again."""
    field = ComprehensionCheckpoint.model_fields["paper_work"]
    assert field.alias == "paperWork"
    rendered = ComprehensionCheckpoint.model_validate(
        {
            **_question().model_dump(by_alias=True, mode="json"),
            "paperWork": paper_work_offer(_question(), teacher_reviewed=True),
        }
    ).model_dump(by_alias=True, mode="json")
    assert rendered["paperWork"]["allowed"] is True


def test_the_default_is_no_offer_rather_than_a_false_one() -> None:
    """A stored payload from before this existed must not promise paper work
    the route would refuse."""
    assert PaperWorkOffer().allowed is False
    assert PaperWorkOffer().instruction is None


def test_every_player_path_goes_through_the_one_renderer() -> None:
    """Including the offline package, which is the half that matters."""
    source = inspect.getsource(lesson_contracts.checkpoint_payloads)
    assert 'rendered["paperWork"] = paper_work_offer(' in source
    # student_checkpoint_payloads, which the offline package uses, delegates
    # here rather than rendering its own.
    student = inspect.getsource(lesson_contracts.student_checkpoint_payloads)
    assert "checkpoint_payloads(" in student
