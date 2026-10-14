import hashlib
import re
from collections import defaultdict


def reading_chunks(
    segment_key: str,
    body: str,
) -> list[dict[str, object]]:
    """Use prose boundaries, never a character budget, to chunk at ingest."""

    text = body.strip()
    if not text:
        return []
    paragraphs = [piece for piece in re.split(r"\n\s*\n", text) if piece.strip()]
    # A paragraph is already a unit identified by the lesson pipeline. For
    # single-paragraph legacy prose, sentence boundaries provide the units.
    grouped = paragraphs if len(paragraphs) > 1 else re.split(r"(?<=[.!?])\s+|\n+", text)
    chunks: list[dict[str, object]] = []
    cursor = 0
    occurrences: dict[str, int] = defaultdict(int)
    for piece in grouped:
        chunk_text = piece.strip()
        if not chunk_text:
            continue
        start = text.find(chunk_text, cursor)
        start = cursor if start < 0 else start
        end = start + len(chunk_text)
        occurrence = occurrences[chunk_text]
        occurrences[chunk_text] += 1
        identity = f"{segment_key}:{chunk_text}"
        if occurrence:
            identity += f":occurrence-{occurrence}"
        digest = hashlib.sha256(identity.encode()).hexdigest()[:20]
        chunks.append(
            {
                "id": f"chunk-{digest}",
                "sequenceOrder": len(chunks) + 1,
                "text": chunk_text,
                "startOffset": start,
                "endOffset": end,
            }
        )
        cursor = end
    return chunks
