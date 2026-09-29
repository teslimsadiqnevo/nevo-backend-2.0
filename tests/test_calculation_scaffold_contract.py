"""The calculation payload the lesson player draws from. SCRUM-177.

The helper only handled two like fractions because the maths lived in the front
end. It should not: the system holds the equation and the visual scaffold, and
the child supplies one thinking step at a time while the answer assembles.

This was built in the student console commits of 27 September. These tests pin
the ticket's rules to it so the shape cannot drift, since SCRUM-185 is built on
top of it.
"""

from __future__ import annotations

import inspect

import pytest

from nevo.content_parsing.service import (
    _calculation_scaffold,
    _validated_calculation_variant,
)

#: The finite drawing vocabulary. A kind outside it is no scaffold at all,
#: because the player has nothing to render for it.
KINDS = ("bar", "number_line", "dots", "array", "place_value")


@pytest.mark.parametrize("kind", KINDS)
def test_every_kind_the_player_implements_is_accepted(kind: str) -> None:
    scaffold = _calculation_scaffold({"kind": kind, "parts": 5, "rows": 1})

    assert scaffold is not None
    assert scaffold["kind"] == kind


def test_a_kind_the_player_cannot_draw_is_no_scaffold_at_all() -> None:
    """Absence is the instruction: the front end infers nothing."""

    assert _calculation_scaffold({"kind": "pie_chart", "parts": 3}) is None
    assert _calculation_scaffold({"parts": 3}) is None
    assert _calculation_scaffold("bar") is None


def test_the_older_names_still_resolve() -> None:
    # Lessons parsed before the vocabulary settled carry these.
    assert _calculation_scaffold({"kind": "fraction_bar", "parts": 5})["kind"] == "bar"
    assert _calculation_scaffold({"kind": "counters", "parts": 5})["kind"] == "dots"


def test_a_scaffold_that_cannot_be_drawn_is_refused_rather_than_approximated() -> None:
    """A calculation the pipeline cannot express carries no scaffold."""

    assert _calculation_scaffold({"kind": "bar", "parts": 0}) is None
    assert _calculation_scaffold({"kind": "bar", "parts": 101}) is None
    assert _calculation_scaffold({"kind": "bar", "parts": 5, "rows": 21}) is None
    assert _calculation_scaffold({"kind": "bar", "parts": "many"}) is None


def test_a_missing_row_count_means_one_row() -> None:
    # Absent or zero is not a malformed scaffold, it is a single row, which is
    # what a fraction bar is.
    assert _calculation_scaffold({"kind": "bar", "parts": 5})["rows"] == 1
    assert _calculation_scaffold({"kind": "bar", "parts": 5, "rows": 0})["rows"] == 1


def test_the_scaffold_carries_what_the_drawing_needs() -> None:
    scaffold = _calculation_scaffold(
        {"kind": "bar", "parts": 5, "rows": 1, "marks": [3, 1], "labels": ["3/5", "1/5"]}
    )

    assert scaffold == {
        "kind": "bar",
        "parts": 5,
        "rows": 1,
        "marks": [3, 1],
        "labels": ["3/5", "1/5"],
    }


def test_a_step_says_what_the_answer_becomes_after_it() -> None:
    """assembles is how the equation builds up one step at a time."""

    variant, refusal = _validated_calculation_variant(
        {
            "expression": "3/5 + 1/5",
            "answer": "4/5",
            "steps": [
                {
                    "stepId": "s1",
                    "prompt": "How many fifths altogether?",
                    "expectedInput": "numeric",
                    "answer": 4,
                    "assembles": "3/5 + 1/5 = ?/5",
                },
                {
                    "stepId": "s2",
                    "prompt": "Write it as a fraction.",
                    "expectedInput": "text",
                    "answer": "4/5",
                    "assembles": "3/5 + 1/5 = 4/5",
                },
            ],
        }
    )

    assert refusal is None
    assert variant is not None
    assert [step["assembles"] for step in variant["steps"]] == [
        "3/5 + 1/5 = ?/5",
        "3/5 + 1/5 = 4/5",
    ]
    assert [step["stepId"] for step in variant["steps"]] == ["s1", "s2"]


def test_a_calculation_never_gets_a_generated_picture() -> None:
    """The conflict the ticket names: a drawn model and a generated image.

    A generated picture beside a deterministic scaffold can disagree with it,
    and a child shown both has no way to know which one to believe.
    """

    from nevo.content_parsing.service import ContentParsingService

    source = inspect.getsource(ContentParsingService._generate_segment_visual)

    assert "LessonContentType.CALCULATION" in source
    assert "visual_variant=None" in source
    # Refused before the generator is consulted, not filtered afterwards.
    assert source.index("CALCULATION") < source.index("generator is None")


def test_the_front_end_is_given_no_maths_to_do() -> None:
    """Every step carries its own answer and the equation state after it."""

    variant, _refusal = _validated_calculation_variant(
        {
            "expression": "3/5 + 1/5",
            "answer": "4/5",
            "steps": [
                {
                    "stepId": "s1",
                    "prompt": "How many fifths?",
                    "expectedInput": "numeric",
                    "answer": 4,
                    "assembles": "3/5 + 1/5 = ?/5",
                },
                {
                    "stepId": "s2",
                    "prompt": "Write it as a fraction.",
                    "expectedInput": "text",
                    "answer": "4/5",
                    "assembles": "3/5 + 1/5 = 4/5",
                },
            ],
        }
    )

    assert variant is not None
    step = variant["steps"][0]
    assert step["answer"] == 4
    assert step["assembles"]
    # Notation stays alongside the scaffold rather than being replaced by it.
    assert variant["expression"] == "3/5 + 1/5"
