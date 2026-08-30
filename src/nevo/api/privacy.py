PRIVATE_INTERACTION_MARKERS = (
    "tap",
    "touch",
    "gesture",
    "dwell",
    "coordinate",
)


def is_private_interaction_key(key: str) -> bool:
    normalized = key.casefold()
    return any(marker in normalized for marker in PRIVATE_INTERACTION_MARKERS) or (
        normalized.endswith("_pattern")
    )
