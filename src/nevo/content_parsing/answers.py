"""Bounded answer equivalence without evaluating expressions or executable input."""

import re
from fractions import Fraction


def normalise(value):
    if isinstance(value, list):
        return sorted((normalise(item) for item in value), key=str)
    if isinstance(value, str):
        return " ".join(value.strip().casefold().split())
    return value


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    text = str(value).strip().replace("\u2212", "-").replace("\u2044", "/")
    if len(text) > 100 or not re.fullmatch(
        r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:\s*/\s*[+-]?\d+)?%?", text
    ):
        return None
    try:
        percent = text.endswith("%")
        result = Fraction(text.removesuffix("%").replace(" ", ""))
        return result / 100 if percent else result
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def _expression(value):
    if not isinstance(value, str) or len(value) > 200:
        return None
    value = value.strip().casefold().replace("\u2212", "-").replace("\u00d7", "*").replace("\u00f7", "/")
    if not re.fullmatch(r"[a-z0-9+*/=().\s-]+", value):
        return None
    return re.sub(r"\s*([+*/=()-])\s*", r"\1", value)


def correct_choice_aliases(expected, options, aliases):
    """Only the correct choice's representations, never a distractor's ID."""
    correct = next(
        (
            option
            for option in options
            if isinstance(option, dict) and normalise(option.get("value")) == normalise(expected)
        ),
        None,
    )
    wrong = [
        option.get("value")
        for option in options
        if isinstance(option, dict) and normalise(option.get("value")) != normalise(expected)
    ]
    label = correct.get("label") if correct else expected
    result = []
    for value in aliases:
        if any(normalise(value) == normalise(other) for other in wrong):
            continue
        if normalise(value) in (normalise(expected), normalise(label)) or (
            (numeric := _number(value)) is not None and numeric == _number(label)
        ):
            result.append(value)
    return result


def answer_matches(answer, question):
    expected = question.get("answerKey")
    if expected is None:
        return None
    alternatives = question.get("acceptedAnswers") or []
    if question.get("options") and not isinstance(expected, list):
        alternatives = correct_choice_aliases(expected, question["options"], alternatives)
    allow_number = question.get("answerType") == "numeric" or not question.get("options")
    for candidate in [expected, *alternatives]:
        if isinstance(answer, bool) != isinstance(candidate, bool):
            continue
        if normalise(answer) == normalise(candidate):
            return True
        if question.get("answerType") == "expression" and (
            expected_expression := _expression(candidate)
        ) is not None and _expression(answer) == expected_expression:
            return True
        if (
            allow_number
            and (a := _number(answer)) is not None
            and (b := _number(candidate)) is not None
            and a == b
        ):
            return True
    return False
