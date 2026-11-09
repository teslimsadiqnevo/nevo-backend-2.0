"""Scaffold labels are words, never a stringified object.

In Speed (508d4fbc) segment 4, the calculation picture's labels held

    ["{'id': 'label_total', 'position': 'top', 'text': 'Total: 120 units
      divided into 2 groups of 60'}"]

a Python dict rendered as text, which a child read on the picture.

The model writes a label either as a string or as an object carrying its text
and its position. The write side called str() on whatever it got. Fixed on the
read as well, so the lessons already holding a dict repr show the words.
"""

from __future__ import annotations

import pytest

from nevo.api.lesson_contracts import label_text
from nevo.content_parsing.service import _labels

#: Exactly what Speed segment 4 has stored.
STORED = (
    "{'id': 'label_total', 'position': 'top', "
    "'text': 'Total: 120 units divided into 2 groups of 60'}"
)
WORDS = "Total: 120 units divided into 2 groups of 60"


def test_the_stored_speed_label_reads_as_words() -> None:
    """The read-side fix, which is what repairs Speed without a backfill."""
    assert label_text(STORED) == WORDS


def test_an_object_label_is_taken_apart_rather_than_stringified() -> None:
    """The write-side fix, so no new lesson stores one."""
    written = {"id": "label_total", "position": "top", "text": WORDS}
    assert label_text(written) == WORDS
    assert _labels([written]) == [WORDS]


def test_no_label_ever_leaves_here_looking_like_code() -> None:
    for shape in (STORED, {"id": "a", "text": WORDS}, WORDS):
        out = label_text(shape)
        for tell in ("{", "}", "'id'", "'position'", "'text'"):
            assert tell not in out, f"{tell} survived in {out!r}"


@pytest.mark.parametrize(
    "written,expected",
    [
        ({"text": "Top"}, "Top"),
        ({"label": "Top"}, "Top"),
        ({"caption": "Top"}, "Top"),
        ({"value": "Top"}, "Top"),
        ({"name": "Top"}, "Top"),
        ({"title": "Top"}, "Top"),
    ],
)
def test_the_field_the_model_chose_does_not_matter(written, expected) -> None:
    assert label_text(written) == expected


@pytest.mark.parametrize(
    "written",
    [
        {"id": "label_total", "position": "top"},
        {},
        {"text": "   "},
        [],
        None,
        True,
        "{not actually a dict}",
    ],
)
def test_a_label_with_no_words_in_it_is_dropped_not_rendered(written) -> None:
    """A child reading "{}" is worse than a picture with one fewer label."""
    assert label_text(written) == ""
    assert _labels([written]) == []


def test_a_plain_string_label_is_untouched_apart_from_spacing() -> None:
    assert label_text("Total: 120") == "Total: 120"
    assert label_text("  spaced   out  ") == "spaced out"


def test_a_mixed_list_keeps_the_good_ones_in_order() -> None:
    assert _labels([{"text": "First"}, "Second", {"id": "nothing-here"}, None, STORED]) == [
        "First",
        "Second",
        WORDS,
    ]


def test_the_hundred_label_cap_survives() -> None:
    assert len(_labels([{"text": f"L{index}"} for index in range(400)])) == 100


def test_something_that_is_not_a_list_yields_nothing() -> None:
    for value in (None, "labels", {"text": "x"}, 7):
        assert _labels(value) == []
