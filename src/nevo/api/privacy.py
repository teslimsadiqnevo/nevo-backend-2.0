PRIVATE_INTERACTION_MARKERS = (
    "tap",
    "touch",
    "gesture",
    "dwell",
    "coordinate",
    "pressure",
    "keystroke",
    "pointermove",
    "swipepath",
)


def is_private_interaction_key(key: str) -> bool:
    normalized = key.casefold()
    compact = "".join(character for character in normalized if character.isalnum())
    return (
        any(marker in normalized or marker in compact for marker in PRIVATE_INTERACTION_MARKERS)
        or (normalized.endswith("_pattern"))
        or compact
        in {"clientx", "clienty", "pagex", "pagey", "screenx", "screeny", "pointerx", "pointery"}
    )


def validate_signal_privacy(value: object) -> None:
    """Reject forbidden keys at every depth, including legacy flattened payloads."""
    remaining = 2048

    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        if depth > 8 or remaining < 0:
            raise ValueError("Signal data is too deeply nested or too large.")
        if isinstance(item, dict):
            keys = {str(key).casefold() for key in item}
            if {"x", "y"} <= keys or any(is_private_interaction_key(str(key)) for key in item):
                raise ValueError("Raw input measurements cannot be submitted as learning events.")
            for child in item.values():
                visit(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                visit(child, depth + 1)

    visit(value, 0)
