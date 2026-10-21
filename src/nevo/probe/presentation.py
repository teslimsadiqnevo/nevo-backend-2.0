"""Standalone placement items and answer-independent presentation order."""

import hashlib
import json
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
        key=lambda option: hashlib.sha256(
            json.dumps(
                ["question-order-v2", seed, option.get("value"), option.get("label")],
                ensure_ascii=True,
                sort_keys=True,
            ).encode()
        ).digest(),
    )
