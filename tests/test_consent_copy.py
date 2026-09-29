"""What a parent is told, and what a school is told, about a waiting consent.

The parent email asked for confirmation without saying what turned on it. The
CEO's copy says what the answer decides, and it is true: student entry refuses
an outstanding consent with consent_pending, so nothing does start before
then.

The administrator's notification said the opposite - that the child kept
learning until the parent replied. A notification that contradicts the product
is worse than none, because a school plans around it.
"""

from __future__ import annotations

import inspect

from nevo.consent.worker import consent_html, consent_message, opening_line

URL = "https://www.nevolearning.com/parent/abc123"


def test_the_parent_is_told_whose_learning_is_waiting() -> None:
    assert opening_line("Zainab") == (
        "Zainab's learning begins as soon as you give permission. Nothing starts before then."
    )


def test_a_child_with_no_first_name_makes_the_same_promise() -> None:
    line = opening_line(None)

    assert line.startswith("Your child's learning begins")
    assert "Nothing starts before then." in line
    # Never a placeholder standing in for a name.
    assert "None" not in line


def test_both_the_text_and_the_html_carry_it() -> None:
    from html import unescape

    assert opening_line("Zainab") in consent_message(URL, "Zainab")
    # The shell escapes the apostrophe, so compare the rendered text.
    assert opening_line("Zainab") in unescape(consent_html(URL, "Zainab"))


def test_the_old_ask_is_gone() -> None:
    body = consent_message(URL, "Zainab")

    # It asked for confirmation without saying what it decided.
    assert "learning data is used" not in body
    assert URL in body
    assert "expires in 7 days" in body


def test_the_struck_sentence_is_not_left_in_the_preview_line() -> None:
    """The line an inbox shows before the mail is opened."""

    assert "Nevo needs your confirmation" not in consent_html(URL, "Zainab")


def test_the_school_is_not_told_the_child_keeps_learning() -> None:
    from nevo.consent.repositories import _notify_school_of_pending_consent

    source = inspect.getsource(_notify_school_of_pending_consent)

    assert "keeps learning" not in source
    assert "cannot start" in source


def test_the_claim_the_copy_makes_is_the_one_the_api_enforces() -> None:
    """The copy promises nothing starts first. Entry has to agree."""

    from nevo.api import student_entry

    source = inspect.getsource(student_entry)

    assert "consent_pending" in source
    assert "HTTP_403_FORBIDDEN" in source
