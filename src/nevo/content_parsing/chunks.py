import hashlib
import re
from collections import defaultdict


def reading_groups(chunks, config):
    """Group immutable source anchors; never invalidate saved annotations."""
    reading, support = config.get("reading") or {}, config.get("support") or {}
    target = 80 if support.get("shorterTextBlocks") else reading.get("segmentWordTarget", 180)
    target = max(80, min(260, int(target)))
    groups, held, words = [], [], 0
    for chunk in chunks:
        size = len(str(chunk["text"]).split())
        if held and words + size > target:
            groups.append(held)
            held, words = [], 0
        held.append(chunk)
        words += size
    if held:
        groups.append(held)
    return [
        {
            "id": "group-"
            + hashlib.sha256(":".join(str(chunk["id"]) for chunk in group).encode()).hexdigest()[
                :20
            ],
            "chunkIds": [chunk["id"] for chunk in group],
            "wordCount": sum(len(str(chunk["text"]).split()) for chunk in group),
            "pauseAfter": bool(support.get("pauseBetweenSegments")),
        }
        for group in groups
    ]


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
    grouped = paragraphs if len(paragraphs) > 1 else sentence_units(text)
    bounded = []
    for paragraph in grouped:
        if len(paragraph.split()) <= 80:
            bounded.append(paragraph)
            continue
        words = list(re.finditer(r"\S+", paragraph))
        index = 0
        while index < len(words):
            end = min(index + 80, len(words))
            if end < len(words):
                boundaries = [
                    position + 1
                    for position in range(index + 39, end)
                    if words[position].group().endswith((".", "!", "?"))
                    and not re.fullmatch(r"\d+[.)]", words[position].group())
                ]
                if boundaries:
                    end = boundaries[-1]
                elif re.fullmatch(r"\d+[.)]", words[end - 1].group()):
                    end -= 1
            bounded.append(paragraph[words[index].start() : words[end - 1].end()])
            index = end
    grouped = bounded
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


def sentence_units(text: str) -> list[str]:
    """A numbered-list marker is not a sentence ending."""
    return re.split(r"(?<!\d\.)(?<=[.!?])\s+|\n+", text)
