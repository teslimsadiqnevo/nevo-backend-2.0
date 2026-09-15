"""The lesson fixtures exist to exercise the parse against real documents.

Each one is plain prose a teacher could have written, which makes it easy to
edit and easy to break: strip the numbered steps out of a worked example and
the calculation variant quietly stops appearing, with nothing to say why. The
assertions here name what each modality feeds on, so an edit that removes it
fails in seconds rather than in a parse run weeks later.
"""

from __future__ import annotations

import re
import sys
from importlib import util
from pathlib import Path

import pytest

from nevo.api.frontend_unblockers import _extract_office_text
from nevo.content_parsing.service import MAX_CHUNK_CHARS, _chunks

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "lessons"
LESSONS = sorted(path for path in FIXTURES.glob("*.md") if path.stem.upper() != "README")
SIMPLE_INTEREST = FIXTURES / "simple-interest-jss3.md"


def _builder():
    script = Path(__file__).resolve().parents[2] / "scripts" / "build_lesson_docx.py"
    spec = util.spec_from_file_location("build_lesson_docx", script)
    module = util.module_from_spec(spec)
    sys.modules.setdefault("build_lesson_docx", module)
    spec.loader.exec_module(module)
    return module


def _section(source: str, heading: str) -> str:
    """The body under a `##` heading, up to the next one."""

    match = re.search(
        rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)",
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, f"the fixture no longer has a '{heading}' section"
    return match.group(1)


def test_there_are_lessons_to_parse() -> None:
    # A library of one lesson tests one lesson's shape.
    assert len(LESSONS) >= 4


@pytest.mark.parametrize("lesson", LESSONS, ids=lambda path: path.stem)
class TestEveryLesson:
    def test_it_has_a_word_document_to_upload(self, lesson: Path) -> None:
        assert lesson.with_suffix(".docx").exists(), "run scripts/build_lesson_docx.py"

    def test_the_document_matches_the_source(self, lesson: Path) -> None:
        # Editing the Markdown and forgetting to rebuild would mean uploading
        # last week's lesson while reviewing this week's in the diff.
        built = _builder().render(lesson.read_text(encoding="utf-8"))
        assert built == lesson.with_suffix(".docx").read_bytes(), (
            "the .docx is stale - run scripts/build_lesson_docx.py"
        )

    def test_it_survives_the_extractor_as_lines(self, lesson: Path) -> None:
        # A Word upload used to arrive as one unbroken line, which cost the
        # parse every heading and step boundary in the document.
        text = _extract_office_text(lesson.with_suffix(".docx").read_bytes())
        assert len(text.splitlines()) > 20

    def test_it_fits_the_model_in_one_chunk(self, lesson: Path) -> None:
        # Split across chunks, the model sees worked examples without the
        # formula that explains them, and the parse degrades for reasons that
        # look like a model failure rather than a sizing one.
        source = lesson.read_text(encoding="utf-8")
        assert len(source) <= MAX_CHUNK_CHARS
        assert len(_chunks(source)) == 1

    def test_it_opens_and_closes_properly(self, lesson: Path) -> None:
        source = lesson.read_text(encoding="utf-8")
        assert source.startswith("# ")
        assert "## Summary" in source

    def test_it_asks_the_learner_something(self, lesson: Path) -> None:
        body = _section(lesson.read_text(encoding="utf-8"), "Practice questions")
        assert len(re.findall(r"^\d+\. ", body, flags=re.MULTILINE)) >= 4

    def test_it_describes_something_worth_drawing(self, lesson: Path) -> None:
        # Visuals come from prose describing a picture. Without a passage like
        # that the model has nothing to hand the image prompt.
        source = lesson.read_text(encoding="utf-8")
        assert re.search(r"\b(picture|imagine|Picture) \w+", source)


class TestSimpleInterest:
    """The only fixture written to force a calculation variant."""

    @pytest.fixture(scope="class")
    def source(self) -> str:
        return SIMPLE_INTEREST.read_text(encoding="utf-8")

    def test_it_opens_on_a_definition(self, source: str) -> None:
        assert "is called **interest**" in _section(source, "What interest is")

    def test_it_carries_arithmetic_a_variant_can_decompose(self, source: str) -> None:
        # A calculation segment is built from steps the model can lift out one
        # at a time and check an answer against.
        for heading in ("Worked example one", "Worked example two"):
            body = _section(source, heading)
            steps = re.findall(r"^Step (\d+)\.", body, flags=re.MULTILINE)
            assert [int(step) for step in steps] == [1, 2, 3, 4, 5], heading
            assert "=" in body, heading

        # The glyphs are the ones a maths teacher types, and the ones the
        # fixture carries, so the comparison has to use them too.
        assert "I = (P × R × T) ÷ 100" in source  # noqa: RUF001

    def test_it_describes_the_bands(self, source: str) -> None:
        assert "rectangle divided into three bands" in source

    def test_it_closes_on_a_summary_the_recap_can_lean_on(self, source: str) -> None:
        assert _section(source, "Summary").strip().endswith("division by 100.")


@pytest.mark.parametrize("lesson", LESSONS, ids=lambda path: path.stem)
def test_a_lesson_does_not_trip_the_compliance_policy(lesson: Path) -> None:
    """A source the gateway will refuse can never be parsed.

    Zero-Tag inspects what the model writes, and the model writes from the
    source. linear-equations-jss3 said two sides of an equation "get the same
    treatment", which is ordinary English and a prohibited term, so the lesson
    was rejected twice and fell back to the deterministic splitter with only
    a JSON decode error to show for it.
    """

    from nevo.ai_gateway.compliance import ZeroTagCompliancePolicy

    result = ZeroTagCompliancePolicy().inspect(lesson.read_text(encoding="utf-8"))
    assert result.allowed, f"{lesson.stem} uses {sorted(result.violations)}"
