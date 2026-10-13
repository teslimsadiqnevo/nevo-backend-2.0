import hashlib
import re


def reading_chunks(
    segment_key: str,
    body: str,
    *,
    target_chars: int = 420,
) -> list[dict[str, object]]:
    """Create stable, ordered meaning-sized prose chunks at ingest."""

    text = body.strip()
    if not text:
        return []
    pieces = [piece.strip() for piece in re.split(r"(?<=[.!?])\s+|\n+", text) if piece.strip()]
    grouped: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current} {piece}".strip()
        if current and len(candidate) > target_chars:
            grouped.append(current)
            current = piece
        else:
            current = candidate
    if current:
        grouped.append(current)
    chunks: list[dict[str, object]] = []
    cursor = 0
    for position, chunk_text in enumerate(grouped, start=1):
        start = text.find(chunk_text, cursor)
        start = cursor if start < 0 else start
        end = start + len(chunk_text)
        digest = hashlib.sha256(f"{segment_key}:{chunk_text}".encode()).hexdigest()[:20]
        chunks.append(
            {
                "id": f"chunk-{digest}",
                "sequenceOrder": position,
                "text": chunk_text,
                "startOffset": start,
                "endOffset": end,
            }
        )
        cursor = end
    return chunks
