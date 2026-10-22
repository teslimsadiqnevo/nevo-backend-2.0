"""Optional observation copy is source-authored, never completion boilerplate."""

import re
from typing import Any


def source_safety(source: str) -> str | None:
    for paragraph in re.split(r"\n\s*\n", source):
        match = re.match(r"\s*Safety\s*:\s*(.+)", paragraph, re.I | re.S)
        if match:
            return match.group(1).strip()
    from nevo.content_parsing.chunks import sentence_units

    warnings = [
        re.sub(r"^Safety\s*:\s*", "", line, flags=re.I)
        for line in sentence_units(source)
        if re.match(r"^Safety\s*:", line, re.I)
    ]
    return " ".join(warnings) or None


def activity_for_delivery(value: Any, source: str) -> Any:
    if not isinstance(value, dict) or "steps" not in value:
        return value
    result = dict(value)
    safety = source_safety(source)
    if safety:
        result["safety"] = safety
    outcome = result.get("outcome")
    if isinstance(outcome, str) and outcome:
        result["outcome"] = re.sub(
            r"^(the|an|a)\b",
            lambda match: match.group()[0].upper() + match.group()[1:],
            outcome,
            flags=re.I,
        )
    return result


LEGACY_DEFAULTS = {
    "you have completed the activity",
    "you have completed this activity",
    "you have completed the source activity",
}


def activity_line(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    line = str(value).strip()
    if line.casefold().rstrip(".! ") in LEGACY_DEFAULTS:
        return None
    return line


def activity_observations(value: dict[str, Any], *, source: str | None = None) -> dict[str, str]:
    result = {}
    for field, raw in (
        ("inProgress", value.get("inProgress", value.get("in_progress"))),
        ("outcome", value.get("outcome")),
    ):
        line = activity_line(raw)
        normalized = " ".join(line.split()) if line else ""
        source_text = " ".join(source.split()) if source is not None else ""
        if line and (
            source is None
            or normalized in source_text
            or normalized[0].swapcase() + normalized[1:] in source_text
        ):
            result[field] = line
    return result


def source_activity_observations(value: Any, source: str) -> Any:
    if not isinstance(value, dict) or "steps" not in value:
        return value
    result = {
        **{
            k: v
            for k, v in value.items()
            if k not in {"outcome", "inProgress", "in_progress", "safety"}
        },
        **activity_observations(value, source=source),
    }
    safety = value.get("safety")
    if (
        isinstance(safety, str)
        and safety.strip()
        and " ".join(safety.split()) in " ".join(source.split())
    ):
        result["safety"] = safety
    return activity_for_delivery(result, "")
