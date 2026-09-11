"""The lesson fixtures exist to exercise every modality of the parse.

Each one is a plain document a teacher could have written, so it is easy to
edit and easy to break: strip the numbered steps out of a worked example and
the calculation variant quietly stops appearing, with nothing to say why. The
assertions here name what each modality feeds on so an edit that removes it
fails in seconds rather than in a parse run weeks later.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from nevo.content_parsing.service import MAX_CHUNK_CHARS, _chunks

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "lessons"
SIMPLE_INTEREST = FIXTURES / "simple-interest-jss3.md"


@pytest.fixture(scope="module")
def simple_interest() -> str:
    return SIMPLE_INTEREST.read_text(encoding="utf-8")


def _section(source: str, heading: str) -> str:
    """The body under a `##` heading, up to the next one."""

    match = re.search(
        rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)",
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, f"the fixture no longer has a '{heading}' section"
    return match.group(1)


def test_fits_the_model_in_one_chunk(simple_interest: str) -> None:
    # Split across chunks the model sees the worked examples without the
    # formula that explains them, and the parse degrades for reasons that
    # look like a model failure rather than a sizing one.
    assert len(simple_interest) <= MAX_CHUNK_CHARS
    assert len(_chunks(simple_interest)) == 1


def test_opens_on_a_definition(simple_interest: str) -> None:
    # The first segment of a lesson is plain text, and it needs something to
    # be plain text about.
    assert "is called **interest**" in _section(simple_interest, "What interest is")


def test_carries_arithmetic_a_calculation_variant_can_decompose(
    simple_interest: str,
) -> None:
    # A calculation segment is built from steps the model can lift out one at
    # a time and check an answer against. Two examples, five steps each, so
    # the pipeline gets more than one chance to produce one.
    for heading in ("Worked example one", "Worked example two"):
        body = _section(simple_interest, heading)
        steps = re.findall(r"^Step (\d+)\.", body, flags=re.MULTILINE)
        assert [int(step) for step in steps] == [1, 2, 3, 4, 5], heading
        assert "=" in body, heading

    # The glyphs are the ones a maths teacher types, and the ones the fixture
    # carries, so the comparison has to use them too.
    assert "I = (P × R × T) ÷ 100" in simple_interest  # noqa: RUF001


def test_describes_something_worth_drawing(simple_interest: str) -> None:
    # Visuals come from prose that describes a picture. Without a passage
    # like this the model has nothing to hand the image prompt.
    assert "rectangle divided into three bands" in simple_interest


def test_offers_questions_for_the_interactive_variant(simple_interest: str) -> None:
    body = _section(simple_interest, "Practice questions")
    questions = re.findall(r"^\d+\. ", body, flags=re.MULTILINE)
    assert len(questions) >= 4


def test_closes_on_a_summary_the_recap_can_lean_on(simple_interest: str) -> None:
    summary = _section(simple_interest, "Summary").strip()
    assert summary.endswith("division by 100.")
