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


def ordered_options(
    options, *, seed, answer_key=None, question_index=None, position_seed=None
):
    """Stable item shuffle with balanced correct-answer positions across a set."""
    ordered = sorted(
        options,
        key=lambda option: hashlib.sha256(
            json.dumps(
                ["question-order-v2", seed, option.get("value"), option.get("label")],
                ensure_ascii=True,
                sort_keys=True,
            ).encode()
        ).digest(),
    )
    if (
        question_index is None
        or isinstance(answer_key, list)
        or answer_key is None
        or len(ordered) < 2
    ):
        return ordered
    correct_index = next(
        (
            index
            for index, option in enumerate(ordered)
            if option.get("value") == answer_key
            and type(option.get("value")) is type(answer_key)
        ),
        None,
    )
    if correct_index is None:
        return ordered
    position_key = position_seed if position_seed is not None else seed
    offset = int.from_bytes(
        hashlib.sha256(str(position_key).encode()).digest()[:4],
        "big",
    )
    target_index = (offset + question_index) % len(ordered)
    correct = ordered.pop(correct_index)
    ordered.insert(target_index, correct)
    return ordered
