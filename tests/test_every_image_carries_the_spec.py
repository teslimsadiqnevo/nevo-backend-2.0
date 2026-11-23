"""Every image request carries the illustration spec, verbatim and last.

Lydia, 22 November: the spec lives in the design system beside the palette
and the radius scale, and it is sent with every image request. Her condition
on the cost comparison was that it be run with the spec applied, not with the
prompts that produced the sloppy images - otherwise she would be judging two
bad pictures and blaming the tier when the prompt was the problem.

The spec's own test is "two images from the same lesson, opened side by side,
should be obviously from the same product". That only holds if the block goes
out unchanged on every call, so these tests pin the wording rather than the
intent: a style instruction reworded per call is how six pictures stop
looking like one set.

Two things in the spec are easy to implement backwards, and both are checked
below. The four house colours govern what Nevo *adds* and never the subject,
because a wrong colour teaches a child something false. And parts are told
apart by shape and position rather than hue, except where the real colour is
the thing being taught.
"""

from __future__ import annotations

import pathlib

from nevo.visuals.service import ILLUSTRATION_STYLE, EducationalImageService

HOUSE_COLOURS = ("#3b3f6e", "#f7f1e6", "#ede8dc", "#9a9ccb")


def _prompt() -> str:
    return EducationalImageService._prompt(
        None,
        "Human circulatory system",
        "Arteries carry oxygenated blood; veins return it.",
        "A labelled diagram of the heart",
    )


def test_the_four_house_colours_are_named_exactly() -> None:
    for colour in HOUSE_COLOURS:
        assert colour in ILLUSTRATION_STYLE, colour


def test_the_house_palette_governs_what_nevo_adds_not_the_subject() -> None:
    """The subject keeps its real colours. Getting this backwards teaches a
    child that veins are violet."""
    assert "true colours" in ILLUSTRATION_STYLE
    added = ILLUSTRATION_STYLE.index("Everything added around the subject")
    palette = ILLUSTRATION_STYLE.index("#3b3f6e")
    assert added < palette, "the palette must be scoped to the added layer"


def test_the_locked_treatment_is_all_there() -> None:
    for rule in (
        "3:2",
        "internal margin",
        "line weight",
        "No shadows",
        "No gradients",
        "never photorealistic",
        "Plain ground",
    ):
        assert rule in ILLUSTRATION_STYLE, rule


def test_no_lettering_is_stated_absolutely() -> None:
    """Mangled lettering is where the sloppiness came from, and layered
    labels are correct, selectable, scalable and translatable."""
    for forbidden in ("no text", "no letters", "no numerals", "no watermark"):
        assert forbidden in ILLUSTRATION_STYLE, forbidden


def test_parts_are_told_apart_by_shape_not_hue() -> None:
    assert "shape, position and placement rather than by colour" in ILLUSTRATION_STYLE
    # With the one exception the spec allows.
    assert "unless the real colour of the subject is itself" in ILLUSTRATION_STYLE


def test_the_block_goes_out_whole_and_last() -> None:
    prompt = _prompt()
    assert ILLUSTRATION_STYLE in prompt, "verbatim, not paraphrased"
    assert prompt.rstrip().endswith(ILLUSTRATION_STYLE.rstrip()), (
        "last, so it is the final word on styling"
    )


def test_the_subject_still_reaches_the_model_before_the_style() -> None:
    prompt = _prompt()
    assert prompt.index("Human circulatory system") < prompt.index("STYLE")


def test_the_spec_is_in_the_repository_as_the_source() -> None:
    """So a change is made in the document first rather than in a string."""
    doc = pathlib.Path(__file__).resolve().parents[1] / "docs" / "illustration-spec.md"
    assert doc.exists()
    text = doc.read_text()
    for colour in HOUSE_COLOURS:
        assert colour.lstrip("#") in text.lower() or colour in text.lower()
