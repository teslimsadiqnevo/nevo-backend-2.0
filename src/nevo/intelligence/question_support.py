"""Give learners time to work before opening question-specific guided help."""


def two_miss_hint(latest, attempts):
    """Question support is independent of lesson-adaptation evidence and history."""
    if latest is None or latest.correct is not False:
        return None
    hint = (latest.question_snapshot or {}).get("hint")
    if not isinstance(hint, str) or not hint.strip():
        return None
    misses = 0
    for row in attempts:
        if row.question_id != latest.question_id:
            continue
        if row.correct is True:
            break
        misses += row.correct is False
        if misses >= 2:
            return hint
    return None


def guidance_deadline(attempts, student):
    """A marked miss can open structured guidance immediately under SCRUM-281."""
    if not attempts or attempts[0].correct is not False:
        return None
    question_id = attempts[0].question_id
    misses = []
    for row in attempts:
        if row.question_id != question_id:
            continue
        if row.correct is not False:
            break
        misses.append(row)
    return min(row.submitted_at for row in misses)
