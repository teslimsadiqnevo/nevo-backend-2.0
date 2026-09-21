"""What a class is called, and when it existed.

Two schools' worth of trouble live in this file. A class name typed twice in
slightly different ways is two classes with the same children split between
them, and nobody notices until a teacher opens a roster holding half a class.
And a class name without a year is next year's JSS 1A colliding with this
year's, so a school in its second year has two classes with one name and one
of them has last year's children in it.

Both are now decided here rather than at each place a class is written, since
class names arrive from a school's own uploaded file as well as by hand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

WHITESPACE = re.compile(r"\s+")

#: "JSS 2A" is a year group and a section; "JSS 2" is only a year group. The
#: trailing letter is the section wherever a school writes one, attached or
#: spaced, because both spellings turn up in the same uploaded file.
NAME = re.compile(r"^(?P<year_group>.*?[0-9]+)\s*(?P<section>[A-Za-z])?$")

#: A Nigerian school year runs from September, so a class created in October
#: 2026 belongs to 2026/2027 and one created in March 2027 to the same.
SESSION_STARTS_IN_MONTH = 9


def normalise_class_name(name: str) -> str:
    """The form two spellings of one class have in common.

    Trimmed, internal whitespace collapsed, case folded. ``jss 1a``,
    ``JSS 1A `` and ``JSS  1A`` are one class, and the database is what
    enforces that rather than each caller remembering to.
    """

    return WHITESPACE.sub(" ", name).strip().casefold()


def academic_session(on: date) -> str:
    """The school year a date falls in, written the way a school writes it."""

    start = on.year if on.month >= SESSION_STARTS_IN_MONTH else on.year - 1
    return f"{start}/{start + 1}"


@dataclass(frozen=True, slots=True)
class ClassName:
    """A class name broken into the parts a console groups and sorts by."""

    name: str
    year_group: str | None
    section: str | None


def parse_class_name(name: str) -> ClassName:
    """Split "JSS 2A" into its year group and section.

    Returns the tidied name with the year group and section where they can be
    read, and None where they cannot: a school may call a class "Sunflower",
    and refusing that would be inventing a rule the school never agreed to.
    """

    tidy = WHITESPACE.sub(" ", name).strip()
    match = NAME.match(tidy)
    if match is None:
        return ClassName(name=tidy, year_group=None, section=None)
    year_group = WHITESPACE.sub(" ", match.group("year_group")).strip()
    section = match.group("section")
    return ClassName(
        name=tidy,
        year_group=year_group or None,
        section=section.upper() if section else None,
    )
