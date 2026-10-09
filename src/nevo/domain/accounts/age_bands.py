"""Which band of schooling a child's age puts them in.

The four names below were already in the product, buried in a match statement
in the mastery engine that decided how many words a minute to expect of a
child. Nothing ever wrote them: the only two places that set a band stored
``str(age)`` - the string "11" - so the match fell through to its default
every single time and every child was read against the same expected reading
speed regardless of age.

So the values are promoted here, where a client can see them, and derived
rather than typed. A band is a function of a date of birth, and a date of
birth is on the roster already. SCRUM-204's rule, one more time: a value
nothing can produce is not a value.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from enum import StrEnum


class AgeBand(StrEnum):
    """The closed set the engine already reasons about."""

    EARLY_PRIMARY = "early_primary"
    UPPER_PRIMARY = "upper_primary"
    JUNIOR_SECONDARY = "junior_secondary"
    SENIOR_SECONDARY = "senior_secondary"


#: The oldest age in each band, in order. Nigerian schooling: primary one
#: begins around six, junior secondary around twelve, senior around fifteen.
#: A child younger than the first band still lands in it rather than nowhere,
#: because a four-year-old reading slowly is not an error to report.
BAND_CEILINGS: tuple[tuple[int, AgeBand], ...] = (
    (8, AgeBand.EARLY_PRIMARY),
    (11, AgeBand.UPPER_PRIMARY),
    (14, AgeBand.JUNIOR_SECONDARY),
)


def band_for_age(age: int | None) -> AgeBand | None:
    """The band an age falls in, or None where the age is unknown."""

    if age is None:
        return None
    for ceiling, band in BAND_CEILINGS:
        if age <= ceiling:
            return band
    return AgeBand.SENIOR_SECONDARY


def age_on(born: date | None, today: date | None = None) -> int | None:
    """Whole years, the way a person counts them."""

    if born is None:
        return None
    now = today or datetime.now(UTC).date()
    return now.year - born.year - ((now.month, now.day) < (born.month, born.day))


def band_for_date_of_birth(born: date | None, today: date | None = None) -> AgeBand | None:
    """The band a date of birth puts a child in. The preferred source."""

    return band_for_age(age_on(born, today))


def coerce_band(stored: str | None, born: date | None = None) -> AgeBand | None:
    """Read a band off an account, whatever is actually written there.

    Three cases, because all three exist in the live database. A real band
    name is returned as it stands. The string form of an age - which is what
    the two write paths used to store - is converted. Anything else falls back
    to the date of birth, which is the source that should have been used all
    along, and then to None.
    """

    value = (stored or "").strip()
    if value:
        try:
            return AgeBand(value.casefold())
        except ValueError:
            pass
        if value.isdigit():
            return band_for_age(int(value))
    return band_for_date_of_birth(born, None)


def band_for_year_group(year_group: str | None) -> AgeBand | None:
    """Use the school's class year when a roster carries no date of birth.

    This is a presentation fallback, not a second stored age. Nigerian schools
    commonly write Primary/P and JSS/JS/SSS/SS with or without spaces, so the
    class name is normalised before matching.
    """

    value = re.sub(r"[^a-z0-9]", "", (year_group or "").casefold())
    match = re.search(r"(\d+)", value)
    year = int(match.group(1)) if match else None
    if value.startswith(("nursery", "reception")):
        return AgeBand.EARLY_PRIMARY
    if value.startswith(("primary", "pry", "p")) and year is not None:
        return AgeBand.EARLY_PRIMARY if year <= 3 else AgeBand.UPPER_PRIMARY
    if value.startswith(("jss", "js", "juniorsecondary")):
        return AgeBand.JUNIOR_SECONDARY
    if value.startswith(("sss", "ss", "seniorsecondary")):
        return AgeBand.SENIOR_SECONDARY
    return None
