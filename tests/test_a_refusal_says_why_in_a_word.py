"""Refusals carry a reason a screen can switch on, not only a sentence.

Two asks, one shape. T8: Ask Nevo's 403 returned a code and a sentence, and
the same code for every role refusal, so a screen that wanted to offer the
roles the account *does* have, or explain that the context rather than the
role was wrong, had nothing to read but prose. T12 / SCRUM-354: a lesson
held by a safety check used one code whether the teacher's own file was the
problem or Nevo's generated content was, so the screen showed one banner for
both - and a teacher reading "held" as "your file was rejected" is behind at
least one of last week's false-positive escalations.

Prose is not an interface. It gets reworded and the screen breaks silently,
which is exactly what a closed set prevents.
"""

from __future__ import annotations

import inspect

from nevo.api import ask_nevo
from nevo.content_parsing import service as parsing
from nevo.domain.ask_nevo.vocabulary import AskNevoRefusalReason


def test_the_refusal_reasons_are_a_closed_set() -> None:
    assert {reason.value for reason in AskNevoRefusalReason} == {
        "role_not_available_to_account",
        "account_cannot_ask",
        "another_learners_context",
    }


def test_asking_in_a_role_you_do_not_have_says_which_roles_you_do() -> None:
    source = inspect.getsource(ask_nevo)
    assert source.count("AskNevoRefusalReason.ROLE_NOT_AVAILABLE_TO_ACCOUNT") == 2
    assert source.count('"availableRoles"') == 2


def test_an_account_that_can_never_ask_is_distinct_from_the_wrong_role() -> None:
    """One is worth offering an alternative for; the other is not, and a
    screen should not show the entry point at all."""
    source = inspect.getsource(ask_nevo)
    assert source.count("AskNevoRefusalReason.ACCOUNT_CANNOT_ASK") == 2


def test_another_learners_context_is_not_a_role_problem() -> None:
    """A role switch does not fix it, so it must not look like a role error."""
    source = inspect.getsource(ask_nevo)
    assert "AskNevoRefusalReason.ANOTHER_LEARNERS_CONTEXT" in source


def test_the_old_codes_are_unchanged() -> None:
    """Clients switch on these today; the reason is an addition, not a swap."""
    source = inspect.getsource(ask_nevo)
    assert '"code": "ask_role_forbidden"' in source
    assert '"code": "student_context_forbidden"' in source


def test_the_route_declares_the_reasons_it_can_return() -> None:
    source = inspect.getsource(ask_nevo)
    assert "role_not_available_to_account" in source
    assert "another_learners_context" in source


def test_a_safety_hold_says_which_check_held_it() -> None:
    """The teacher's own file, or Nevo's generated content. Not both at once."""
    source = inspect.getsource(parsing)
    assert '"heldAtCheck"' in source
    assert '"lesson_source"' in source
    assert '"generated_content"' in source
    # The existing code must stay put for the clients already reading it.
    assert '"code": "lesson_text_blocked_by_safety"' in source
