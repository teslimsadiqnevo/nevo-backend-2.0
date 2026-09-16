"""A chunk has to be answerable within the budget for answering it.

These were two independent constants and they drifted into contradiction: a
chunk was allowed to be 24,000 characters while the answer to it was capped at
16,384 tokens, which is roughly a third of what 24,000 characters needs. Any
document long enough to fill a chunk was cut off mid-object, and the whole
lesson fell back to the deterministic splitter with a JSON decode error as the
only clue.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nevo.api.frontend_unblockers import _extract_office_text
from nevo.content_parsing.service import (
    CHUNK_HEADROOM,
    MAX_CHUNK_CHARS,
    OUTPUT_TOKENS_PER_SOURCE_CHAR,
    PARSE_OUTPUT_TOKENS,
    _chunks,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "lessons"
LESSONS = sorted(FIXTURES.glob("*.docx"))


def test_a_full_chunk_fits_the_answer_budget() -> None:
    needed = MAX_CHUNK_CHARS * OUTPUT_TOKENS_PER_SOURCE_CHAR

    assert needed <= PARSE_OUTPUT_TOKENS, (
        f"a full chunk needs ~{needed:,.0f} tokens but only {PARSE_OUTPUT_TOKENS:,} "
        "are allowed, so the model is cut off mid-answer"
    )


def test_there_is_room_left_for_a_verbose_run() -> None:
    # The ratio is an average over four documents. A dense one that runs long
    # should still land inside the budget rather than only just missing it.
    spare = PARSE_OUTPUT_TOKENS - MAX_CHUNK_CHARS * OUTPUT_TOKENS_PER_SOURCE_CHAR

    assert spare / PARSE_OUTPUT_TOKENS >= 0.15
    assert CHUNK_HEADROOM < 1.0


def test_the_cap_is_derived_rather_than_chosen() -> None:
    # The fault was two numbers set by hand that nothing kept in agreement.
    assert MAX_CHUNK_CHARS == int(
        PARSE_OUTPUT_TOKENS / OUTPUT_TOKENS_PER_SOURCE_CHAR * CHUNK_HEADROOM
    )


@pytest.mark.parametrize("lesson", LESSONS, ids=lambda path: path.stem)
def test_every_fixture_still_parses_as_one_chunk(lesson: Path) -> None:
    # A smaller cap is only worth having if a real lesson still arrives whole:
    # split across chunks, the model sees worked examples without the formula
    # that explains them.
    text = _extract_office_text(lesson.read_bytes())

    assert len(_chunks(text)) == 1, f"{lesson.stem} is {len(text):,} chars"


def test_a_long_document_is_split_rather_than_truncated() -> None:
    paragraph = "Simple interest is worked out on the original principal. " * 40
    source = "\n\n".join([paragraph] * 12)
    assert len(source) > MAX_CHUNK_CHARS

    chunks = _chunks(source)

    assert len(chunks) > 1
    assert all(len(chunk) <= MAX_CHUNK_CHARS for chunk in chunks)


def test_the_ratio_matches_what_was_measured_in_production() -> None:
    """4,612 characters came back as 9,004 output tokens on 16 September.

    Recorded as a test so that raising the token budget without revisiting
    this, or vice versa, fails here rather than in a teacher's upload.
    """
    measured = 9004 / 4612

    assert OUTPUT_TOKENS_PER_SOURCE_CHAR >= measured
