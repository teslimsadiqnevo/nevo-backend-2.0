"""Optional observation copy is source-authored, never completion boilerplate."""

LEGACY_DEFAULTS = {
    "you have completed the activity",
    "you have completed this activity",
    "you have completed the source activity",
}


def activity_line(value):
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if value.casefold().rstrip(".! ") in LEGACY_DEFAULTS:
        return None
    return value


def activity_observations(value, *, source=None):
    result = {}
    for field, raw in (
        ("inProgress", value.get("inProgress", value.get("in_progress"))),
        ("outcome", value.get("outcome")),
    ):
        line = activity_line(raw)
        if line and (source is None or " ".join(line.split()) in " ".join(source.split())):
            result[field] = line
    return result


def source_activity_observations(value, source):
    if not isinstance(value, dict) or "steps" not in value:
        return value
    return {
        **{k: v for k, v in value.items() if k not in {"outcome", "inProgress", "in_progress"}},
        **activity_observations(value, source=source),
    }
