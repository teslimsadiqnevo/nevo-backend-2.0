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


def answer_matches(answer, question):
    expected = question.get("answerKey")
    if expected is None:
        return None
    alternatives = question.get("acceptedAnswers") or []
    allow_number = question.get("answerType") == "numeric" or not question.get("options")
    for candidate in [expected, *alternatives]:
        if isinstance(answer, bool) != isinstance(candidate, bool):
            continue
        if normalise(answer) == normalise(candidate):
            return True
        if (
            allow_number
            and (a := _number(answer)) is not None
            and (b := _number(candidate)) is not None
            and a == b
        ):
            return True
    return False
