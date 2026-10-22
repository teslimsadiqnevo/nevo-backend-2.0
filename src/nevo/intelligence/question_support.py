"""Give learners time to work before opening question-specific guided help."""

from datetime import timedelta

from nevo.domain.accounts.age_bands import AgeBand, coerce_band


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
    """Use the current question's consecutive misses, not a lifetime error count."""
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
    if len(misses) < 3:
        return None
    band = coerce_band(student.age_band, student.date_of_birth)
    seconds = {
        AgeBand.EARLY_PRIMARY: 45,
        AgeBand.UPPER_PRIMARY: 45,
        AgeBand.JUNIOR_SECONDARY: 60,
        AgeBand.SENIOR_SECONDARY: 90,
    }.get(band, 90)
    # No normalized attention measure is currently stored; do not invent one to shorten it.
    return min(row.submitted_at for row in misses) + timedelta(seconds=seconds)
