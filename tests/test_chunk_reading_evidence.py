import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from nevo.api.insights import _chunk_rereads
from nevo.content_parsing.chunks import reading_chunks
from nevo.domain.signal_events.vocabulary import SignalEventType


def test_chunks_follow_paragraphs_and_keep_exact_offsets():
    first = "One sentence. " * 60
    body = f"{first.strip()}\n\nA new idea begins here."
    chunks = reading_chunks("segment", body)
    assert len(chunks) == 3
    assert all(len(chunk["text"].split()) <= 80 for chunk in chunks)
    assert " ".join(chunk["text"] for chunk in chunks[:2]) == first.strip()
    for chunk in chunks:
        assert body[chunk["startOffset"] : chunk["endOffset"]] == chunk["text"]
    assert chunks == reading_chunks("segment", body)


def test_duplicate_prose_has_distinct_stable_ids():
    chunks = reading_chunks("segment", "Remember this.\n\nRemember this.")
    assert len({item["id"] for item in chunks}) == 2
    assert chunks == reading_chunks("segment", "Remember this.\n\nRemember this.")


def test_extracted_number_with_newline_or_blank_line_stays_with_instruction():
    for separator in ("\n", "\n\n", " \n\n"):
        body = f"Stir the salt water.\n5.{separator}Put one strip into each cup.\n6.\nWait."
        chunks = reading_chunks("segment", body)
        assert all(not re.search(r"\b\d+[.)]$", row["text"]) for row in chunks)
        for row in chunks:
            assert body[row["startOffset"] : row["endOffset"]] == row["text"]


def test_reentry_counts_once_until_the_chunk_is_passed_again():
    student_id, session_id = uuid4(), uuid4()
    now = datetime.now(UTC)

    def event(action, index, session=session_id, form="tablet"):
        return SimpleNamespace(
            student_id=student_id,
            session_id=session,
            event_type=SignalEventType.READING_CHUNK_VIEWED,
            timestamp=now + timedelta(seconds=index),
            event_data={"chunkId": "chunk-1", "action": action, "formFactor": form},
        )

    events = [
        event("entered", 0),
        event("passed", 1),
        event("entered", 2),
        event("entered", 3),
        event("passed", 4),
        event("entered", 5),
        event("entered", 6, uuid4()),
        event("entered", 7, form="desktop"),
    ]
    assert _chunk_rereads(events) == [
        {"chunkId": "chunk-1", "rereadCount": 2, "timeInChunkMs": None}
    ]


def test_no_chunk_evidence_returns_no_attribution():
    assert _chunk_rereads([]) == []
