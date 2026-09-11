"""The lesson fixtures exist to exercise every modality of the parse.

Each one is a plain lesson a teacher could have written, so it is easy to edit
and easy to break: strip the numbered steps out of a worked example and the
calculation variant quietly stops appearing, with nothing to say why. The
assertions here name what each modality feeds on so an edit that removes it
fails in seconds rather than in a parse run weeks later.

The .docx beside the Markdown is what actually gets uploaded, so the checks
run against the text the production extractor pulls back out of it, not
against the Markdown the author typed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from nevo.api.frontend_unblockers import _extract_office_text, _extract_text
from nevo.content_parsing.service import MAX_CHUNK_CHARS, _chunks

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "lessons"
SIMPLE_INTEREST_MD = FIXTURES / "simple-interest-jss3.md"
SIMPLE_INTEREST_DOCX = FIXTURES / "simple-interest-jss3.docx"


@pytest.fixture(scope="module")
def lesson() -> str:
    """The lesson as the parse receives it: read back out of the .docx."""

    return _extract_text(SIMPLE_INTEREST_DOCX.name, SIMPLE_INTEREST_DOCX.read_bytes())


def _section(source: str, heading: str) -> str:
    """The lines under a heading, up to the next one."""

    headings = [
        "What interest is",
        "The formula",
        "Worked example one",
        "Worked example two",
        "Finding the rate when you know the interest",
        "A common mistake",
        "Practice questions",
        "Summary",
    ]
    assert heading in headings, f"unknown heading {heading!r}"
    lines = source.splitlines()
    assert heading in lines, f"the fixture no longer has a '{heading}' section"
    start = lines.index(heading) + 1
    rest = [line for line in lines[start:] if line in headings]
    end = lines.index(rest[0], start) if rest else len(lines)
    return "\n".join(lines[start:end])


def test_the_docx_is_what_the_markdown_says_it_is() -> None:
    # The .docx is generated, so it can fall behind the source it came from.
    # Rebuild it in memory and compare what a reader would actually see.
    from scripts.build_lesson_docx import render

    rebuilt = _extract_office_text(render(SIMPLE_INTEREST_MD.read_text(encoding="utf-8")))
    assert rebuilt == _extract_office_text(SIMPLE_INTEREST_DOCX.read_bytes()), (
        "simple-interest-jss3.docx is stale — rebuild it with "
        "`python scripts/build_lesson_docx.py tests/fixtures/lessons/*.md`"
    )


def test_survives_the_upload_with_its_lines_intact(lesson: str) -> None:
    # Flattened to a single line the document still reads, but the parse can
    # no longer tell a heading from a sentence or one step from the next.
    assert len(lesson.splitlines()) > 40
    assert "Worked example one" in lesson.splitlines()


def test_fits_the_model_in_one_chunk(lesson: str) -> None:
    # Split across chunks the model sees the worked examples without the
    # formula that explains them, and the parse degrades for reasons that
    # look like a model failure rather than a sizing one.
    assert len(lesson) <= MAX_CHUNK_CHARS
    assert len(_chunks(lesson)) == 1


def test_opens_on_a_definition(lesson: str) -> None:
    # The first segment of a lesson is plain text, and it needs something to
    # be plain text about.
    assert "is called interest." in _section(lesson, "What interest is")


def test_carries_arithmetic_a_calculation_variant_can_decompose(lesson: str) -> None:
    # A calculation segment is built from steps the model can lift out one at
    # a time and check an answer against. Two examples, five steps each, so
    # the pipeline gets more than one chance to produce one.
    for heading in ("Worked example one", "Worked example two"):
        body = _section(lesson, heading)
        steps = re.findall(r"^Step (\d+)\.", body, flags=re.MULTILINE)
        assert [int(step) for step in steps] == [1, 2, 3, 4, 5], heading
        # Each step is followed by the arithmetic it stands for, on its own
        # line. That line is what becomes a step in the variant.
        arithmetic = r"^Step 2\..*\n^\d+ × \d+ = \d+$"  # noqa: RUF001
        assert re.search(arithmetic, body, flags=re.MULTILINE), heading

    # The glyphs are the ones a maths teacher types, and the ones the lesson
    # carries, so the comparison has to use them too.
    assert "I = (P × R × T) ÷ 100" in lesson  # noqa: RUF001


def test_describes_something_worth_drawing(lesson: str) -> None:
    # Visuals come from prose that describes a picture. Without a passage
    # like this the model has nothing to hand the image prompt.
    assert "rectangle divided into three bands" in lesson


def test_offers_questions_for_the_interactive_variant(lesson: str) -> None:
    body = _section(lesson, "Practice questions")
    questions = re.findall(r"^\d+\. ", body, flags=re.MULTILINE)
    assert len(questions) >= 4


def test_closes_on_a_summary_the_recap_can_lean_on(lesson: str) -> None:
    assert _section(lesson, "Summary").strip().endswith("division by 100.")
