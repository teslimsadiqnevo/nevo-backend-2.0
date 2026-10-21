"""Standalone placement items and answer-independent presentation order."""

import hashlib
import re


def standalone_question(question: str) -> bool:
    return not re.search(
        r"\b(?:in|from|using|see|refer to|as shown in)\s+(?:the\s+)?"
        r"(?:worked example|example above|diagram|figure|table above|passage|previous section)\b",
        question,
        re.IGNORECASE,
    )


def ordered_options(options, *, seed):
    """Stable within a pupil/item, independent of the correct answer's value."""
    return sorted(
        options,
        key=lambda option: hashlib.sha256(f"{seed}:{option.get('value')}".encode()).digest(),
    )
