"""Whether what a child typed counts. SCRUM-185.

No symbolic engine, no per-subject checker, no maths in the front end. Every
form that counts as correct is enumerated at upload, from that lesson, and the
runtime does nothing cleverer than match against the list. That is the whole
reason it works for chemistry and Yoruba and long division alike.
"""

from __future__ import annotations

import pytest

from nevo.content_parsing.service import _accepted_forms
from nevo.domain.steps.vocabulary import SupportLevel, WorkingLayout
from nevo.steps.answers import first_match, matches, normalise


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ("0.5", "0.5"),
        ("  0.5  ", "0.5"),
        ("0.5.", "0.5"),
        ("X + 1", "x+1"),
        ("1 + x", "1+x"),
        # Spacing around an operator is typing, not meaning.
        ("2 = 2", "2=2"),
    ],
)
def test_typing_is_folded_and_meaning_is_not(entry: str, expected: str) -> None:
    assert normalise(entry) == expected


def test_a_unit_keeps_its_space() -> None:
    """Collapsing every space would fold "2 x" into "2x", which differs."""

    assert normalise("5 m/s") == "5 m/s"
    assert normalise("5 m / s") == "5 m/s"


def test_a_keyboard_minus_is_a_minus() -> None:
    # A textbook's minus sign against a keyboard's hyphen.
    assert normalise("\u22125") == normalise("-5")
    assert normalise("3 \u00d7 4") == normalise("3*4")


@pytest.mark.parametrize(
    ("entry", "accepted"),
    [
        ("0.5", ["1/2", "0.5", "50%"]),
        ("1/2", ["1/2", "0.5", "50%"]),
        ("50%", ["1/2", "0.5", "50%"]),
        ("X + 1", ["x+1", "1+x"]),
        ("1+X", ["x+1", "1+x"]),
    ],
)
def test_every_stored_form_is_accepted(entry: str, accepted: list[str]) -> None:
    assert matches(entry, accepted)


def test_something_that_is_not_on_the_list_is_wrong() -> None:
    assert not matches("7", ["4"])
    assert not matches("", ["4"])


def test_a_step_with_no_stored_forms_accepts_nothing() -> None:
    """Correct rather than permissive.

    An empty list means the pipeline could not enumerate the answers, and a
    step that accepts anything teaches a child that anything is right.
    """

    assert not matches("4", [])
    assert not matches("anything at all", [])


def test_the_matched_form_is_recoverable_for_the_record() -> None:
    assert first_match("0.5", ["1/2", "0.5", "50%"]) == "0.5"
    assert first_match("  1/2 ", ["1/2", "0.5"]) == "1/2"
    assert first_match("9", ["1/2"]) is None


def test_the_answer_is_always_among_the_accepted_forms() -> None:
    """A generated list that omits its own answer marks a correct child wrong."""

    assert "4" in _accepted_forms({}, 4)
    assert "4/5" in _accepted_forms({"accepted": ["0.8"]}, "4/5")


def test_duplicate_forms_are_collapsed_once_normalised() -> None:
    forms = _accepted_forms({"accepted": ["0.5", "0.5 ", " 0.5"]}, "0.5")

    assert forms == ["0.5"]


def test_the_stored_list_is_bounded() -> None:
    forms = _accepted_forms({"accepted": [str(n) for n in range(100)]}, None)

    assert len(forms) <= 40


def test_the_support_ladder_has_a_rung_for_what_cannot_be_enumerated() -> None:
    """Coverage is measured, not assumed: 22 of 344 topics reach the floor."""

    assert set(SupportLevel) == {
        SupportLevel.BUILD,
        SupportLevel.CHOOSE,
        SupportLevel.REVEAL,
        SupportLevel.ORDINARY,
    }
    # The floor is an ordinary segment, not a bad approximation of the others.
    assert SupportLevel.ORDINARY == "ordinary"


def test_a_layout_is_emitted_so_every_subject_is_not_a_column_of_equations() -> None:
    assert set(WorkingLayout) == {
        WorkingLayout.EQUATION,
        WorkingLayout.COLUMN,
        WorkingLayout.STEPS,
        WorkingLayout.TABLE,
    }


def test_the_segment_records_which_rung_it_got() -> None:
    import nevo.db.models  # noqa: F401
    from nevo.db.base import Base

    columns = Base.metadata.tables["lesson_segments"].columns

    assert "support_level" in columns
    assert "working_layout" in columns
