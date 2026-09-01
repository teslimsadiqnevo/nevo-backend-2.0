import re
from dataclasses import dataclass, field
from enum import StrEnum

BULLET = re.compile(r"^\s*[-*•·]\s+(?P<text>.+)$")
NUMBERED = re.compile(r"^\s*(?P<number>\d{1,2})[.)]\s+(?P<text>.+)$")
HEADING = re.compile(r"^\s*(?P<hashes>#{1,6})\s+(?P<text>.+?)\s*#*$")
# A short line ending in a colon reads as a heading even without a hash, which
# is how models usually introduce a list in prose.
COLON_HEADING = re.compile(r"^\s*(?P<text>[^\n]{3,60}):\s*$")
INLINE_MARKERS = re.compile(r"(\*\*|__|\*|_|`)")
TRAILING_PUNCT = re.compile(r"\s+([,.;:!?])")


class AnswerBlockType(StrEnum):
    """The shapes an assistant answer can take.

    Deliberately small. A renderer that only understands PARAGRAPH can print
    every block's text and still be correct, which is what makes this safe to
    add to a client that has not adopted it.
    """

    PARAGRAPH = "paragraph"
    BULLETS = "bullets"
    STEPS = "steps"
    HEADING = "heading"


class AnswerFormat(StrEnum):
    """What the model actually produced, as detected."""

    PLAIN = "plain"
    STRUCTURED = "structured"


@dataclass(frozen=True, slots=True)
class AnswerBlock:
    type: AnswerBlockType
    text: str = ""
    items: tuple[str, ...] = ()
    level: int = 0


@dataclass(frozen=True, slots=True)
class StructuredAnswer:
    """A model answer normalised into renderable blocks.

    ``plain_text`` is always populated so a client that wants a single string
    never has to walk the blocks.
    """

    blocks: tuple[AnswerBlock, ...] = field(default_factory=tuple)
    plain_text: str = ""
    format: AnswerFormat = AnswerFormat.PLAIN


def strip_inline_markup(value: str) -> str:
    """Remove emphasis markers, leaving readable text.

    Emphasis is dropped rather than represented. A client that renders the
    text verbatim then never shows a stray '**' to a teacher, which is the
    failure this exists to prevent. If emphasis is wanted later it can be
    added as spans without changing what is already here.
    """
    cleaned = INLINE_MARKERS.sub("", value)
    cleaned = TRAILING_PUNCT.sub(r"\1", cleaned)
    return " ".join(cleaned.split()).strip()


def structure_answer(answer: str) -> StructuredAnswer:
    """Normalise a model answer into blocks a client can render in any form.

    The model is not constrained to one output format, because constraining it
    makes answers worse and drifts anyway. Instead whatever it produces —
    plain prose, markdown bullets, numbered steps, headings, or a mixture — is
    parsed here, once, on the server. Every client then renders the same
    structure rather than each one parsing prose differently.
    """
    text = (answer or "").replace("\r\n", "\n").strip()
    if not text:
        return StructuredAnswer()

    blocks: list[AnswerBlock] = []
    pending_paragraph: list[str] = []
    pending_items: list[str] = []
    pending_kind: AnswerBlockType | None = None

    def flush_paragraph() -> None:
        if pending_paragraph:
            body = strip_inline_markup(" ".join(pending_paragraph))
            if body:
                blocks.append(AnswerBlock(type=AnswerBlockType.PARAGRAPH, text=body))
            pending_paragraph.clear()

    def flush_items() -> None:
        nonlocal pending_kind
        if pending_items and pending_kind is not None:
            blocks.append(AnswerBlock(type=pending_kind, items=tuple(pending_items)))
        pending_items.clear()
        pending_kind = None

    for raw_line in text.split("\n"):
        line = raw_line.rstrip()
        if not line.strip():
            flush_items()
            flush_paragraph()
            continue

        if heading := HEADING.match(line):
            flush_items()
            flush_paragraph()
            body = strip_inline_markup(heading.group("text"))
            if body:
                blocks.append(
                    AnswerBlock(
                        type=AnswerBlockType.HEADING,
                        text=body,
                        level=len(heading.group("hashes")),
                    )
                )
            continue

        if bullet := BULLET.match(line):
            flush_paragraph()
            if pending_kind is not AnswerBlockType.BULLETS:
                flush_items()
                pending_kind = AnswerBlockType.BULLETS
            body = strip_inline_markup(bullet.group("text"))
            if body:
                pending_items.append(body)
            continue

        if numbered := NUMBERED.match(line):
            flush_paragraph()
            if pending_kind is not AnswerBlockType.STEPS:
                flush_items()
                pending_kind = AnswerBlockType.STEPS
            body = strip_inline_markup(numbered.group("text"))
            if body:
                pending_items.append(body)
            continue

        if not pending_paragraph and (colon := COLON_HEADING.match(line)):
            flush_items()
            body = strip_inline_markup(colon.group("text"))
            if body:
                blocks.append(
                    AnswerBlock(type=AnswerBlockType.HEADING, text=body, level=3)
                )
            continue

        flush_items()
        pending_paragraph.append(line.strip())

    flush_items()
    flush_paragraph()

    if not blocks:
        body = strip_inline_markup(text)
        blocks = [AnswerBlock(type=AnswerBlockType.PARAGRAPH, text=body)] if body else []

    detected = (
        AnswerFormat.PLAIN
        if all(block.type is AnswerBlockType.PARAGRAPH for block in blocks)
        else AnswerFormat.STRUCTURED
    )
    return StructuredAnswer(
        blocks=tuple(blocks),
        plain_text=_as_plain_text(blocks),
        format=detected,
    )


def _as_plain_text(blocks: list[AnswerBlock]) -> str:
    """Flatten blocks back to prose, for clients that want one string."""
    parts: list[str] = []
    for block in blocks:
        if block.type in (AnswerBlockType.PARAGRAPH, AnswerBlockType.HEADING):
            parts.append(block.text)
        elif block.type is AnswerBlockType.BULLETS:
            parts.extend(f"• {item}" for item in block.items)
        elif block.type is AnswerBlockType.STEPS:
            parts.extend(
                f"{index}. {item}" for index, item in enumerate(block.items, start=1)
            )
    return "\n".join(part for part in parts if part)
