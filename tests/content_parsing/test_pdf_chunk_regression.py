import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from nevo.api import product_learning
from nevo.api.product_learning import _failed_pages
from nevo.content_parsing.entities import SourcePage
from nevo.content_parsing.service import (
    MAX_CHUNK_CHARS,
    _chunks,
    _fallback_segments,
    _missing_text_pages,
)


@pytest.mark.parametrize("separator", ["\n", "\n\n", " ", ""])
def test_even_a_single_oversized_line_cannot_bypass_budget(separator):
    source = separator.join(["abcdefghij" * 500] * 8)
    chunks = _chunks(source)
    assert len(chunks) > 1
    assert max(map(len, chunks)) <= MAX_CHUNK_CHARS
    assert "".join(chunks) == source.strip()


def test_27_page_pdf_without_blank_lines_keeps_all_text_and_page_boundaries():
    source = "\n".join(
        f"[Page {page}]\nExam guide chapter {page}\n" + "A useful teaching sentence. " * 48
        for page in range(1, 28)
    )
    chunks = _chunks(source)
    assert max(map(len, chunks)) <= MAX_CHUNK_CHARS
    assert "".join(chunks) == source.strip()
    assert len(chunks) > 1
    fallback = _fallback_segments(source, sequence_offset=0)
    assert len(fallback) >= 27
    assert all(len(segment.body) <= 1800 for segment in fallback)
    assert all(not re.fullmatch(r"\[Page \d+\]", segment.title or "") for segment in fallback)
    assert "".join("".join(segment.body.split()) for segment in fallback) == "".join(source.split())


def test_failed_pages_are_extraction_failures_not_ai_formatting_failures():
    assert _failed_pages(
        {
            "reviewNotes": [
                {"code": "ai_parse_fallback", "pageNumbers": list(range(1, 28))},
                {"code": "page_text_missing", "pageNumbers": [3, 8]},
            ]
        }
    ) == [3, 8]
    assert _missing_text_pages("[Page 1]\nSome text\n[Page 2]\n \n[Page 3]\nMore text") == [2]


@pytest.mark.asyncio
async def test_page_retry_does_not_replace_a_full_upload_with_only_the_selected_page(monkeypatch):
    school_id = uuid4()
    job = SimpleNamespace(
        school_id=school_id,
        status="ready",
        undo_stack=[],
        structure={},
        stage="ready_to_assign",
        error_message=None,
        failure_reason=None,
        incident_id=None,
        completed_at=None,
    )
    session = SimpleNamespace(
        get=AsyncMock(side_effect=[job, SimpleNamespace(filename="guide.pdf", content=b"pdf")]),
        commit=AsyncMock(),
    )
    monkeypatch.setattr(
        product_learning,
        "require_school_actor",
        AsyncMock(return_value=SimpleNamespace(id=uuid4(), school_id=school_id)),
    )
    monkeypatch.setattr(
        product_learning, "_extract_pdf_pages", lambda *_: [SourcePage(2, "page two")]
    )
    monkeypatch.setattr(
        product_learning, "_extract_text", lambda *_: "page one\npage two\npage three"
    )
    start = Mock()
    monkeypatch.setattr(product_learning, "_parse_into_job", start)
    await product_learning.retry_upload_pages(
        uuid4(), product_learning.RetryPagesRequest(pageNumbers=[2]), None, session, None, None
    )
    request = start.call_args.kwargs["request"]
    assert request.source_text == "page one\npage two\npage three"
    assert request.source_metadata["retryPageNumbers"] == [2]
