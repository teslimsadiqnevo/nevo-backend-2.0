"""A lesson counts when we judge it finished, not when the app claims it.

Lydia, 22 November: "18 is the number and the definition is the final check
taken and marked, stored as our decision rather than the app's claim.
Twenty-two of forty-one completed sittings having no recorded answer is the
whole argument."

completion_status is the player's declaration, and it stays exactly that -
a record of what the app told us, which we do not get to edit. Whether a
lesson counts towards a learner's profile is now ours, written to
verified_complete_at.

The rule is not settled and these tests say so rather than hiding it. The
three candidates give 18, 27 and 31, and 18 is the only one that still
consults the app's claim - so her number and her principle cannot both hold.
Until she picks, the rule is the one that produces her figure.
"""

from __future__ import annotations

import inspect

from nevo.db.models.signal_event import LessonSession
from nevo.intelligence import accommodation_repositories, finished_lessons


def test_the_sitting_can_hold_our_own_judgement() -> None:
    column = LessonSession.__table__.c.verified_complete_at
    assert column.nullable, "not judged finished is not the same as not finished"


def test_the_rule_is_one_named_place() -> None:
    """So settling it is a one-word change rather than a hunt."""
    assert finished_lessons.RULE in {"app_and_check", "ended_and_check", "check_only"}
    source = inspect.getsource(finished_lessons)
    assert "18" in source and "27" in source and "31" in source, (
        "the three counts belong beside the choice, or nobody can make it"
    )


def test_the_rule_is_marked_evidence_alone() -> None:
    """Settled by Lydia on 22 November at 31, not the 27 she first chose.

    She asked whether the "ended" half was ours or the app's. It is the
    app's: three of the four paths that set ended_at are the app telling us,
    and one of those lets the client supply the timestamp itself. So by her
    own principle it came out, and what the number counts is lessons that
    gave us marked evidence - a learner who answered six checks and
    abandoned at segment five produced six checks of evidence.
    """
    assert finished_lessons.RULE == "check_only"


def test_the_evidence_is_a_markable_answer_not_a_right_one() -> None:
    """A wrong answer is still a lesson the child did."""
    source = inspect.getsource(finished_lessons._marked_check_exists)
    assert "correct.is_not(None)" in source
    assert "correct.is_(True)" not in source
    assert '("checkpoint", "assessment")' in source


def test_the_judgement_clears_as_well_as_sets() -> None:
    """A sitting that stops qualifying must stop counting. A judgement that
    only ever accumulates is not a judgement."""
    source = inspect.getsource(finished_lessons.judge_finished)
    assert "sitting.verified_complete_at = None" in source


def test_the_apps_claim_is_never_edited() -> None:
    source = inspect.getsource(finished_lessons)
    assert "completion_status =" not in source, (
        "completion_status records what the app said; we do not rewrite it"
    )


def test_the_profile_counts_our_judgement_not_the_claim() -> None:
    """An accommodation confirmed from lessons half of which are noise is an
    accommodation applied to a child on no evidence."""
    source = inspect.getsource(accommodation_repositories)
    assert "verified_complete_at.is_not(None)" in source
    assert "completion_status == LessonCompletionStatus.COMPLETED" not in source


def test_the_rejudge_script_refuses_to_pick_the_rule_for_her() -> None:
    import pathlib

    script = (
        pathlib.Path(__file__).resolve().parents[1]
        / "scripts"
        / "rejudge_finished_lessons.py"
    )
    source = script.read_text()
    assert "default=None" in source
    assert "app-and-check" in source and "ended-and-check" in source
    # And it clears, for the same reason judge_finished does.
    assert "verified_complete_at = null" in source
