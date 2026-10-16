import re


def clean_lesson_description(value: object) -> str | None:
    """A short content preview, never a duration breakdown."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text or re.search(
        r"\b(?:total|segment\s+\d+)\s*[:=(]?\s*\d+(?:\.\d+)?\s*(?:min(?:ute)?s?|hours?)\b",
        text,
        re.IGNORECASE,
    ):
        return None
    if len(text) <= 360:
        return text
    first_sentence = re.split(r"(?<=[.!?])\s+", text)[0]
    return first_sentence if len(first_sentence) <= 360 else None
