"""Turning teacher rows from a spreadsheet into teachers with subjects.

Two rules do the work here, and both are about not fusing two people into one.

Rows merge on email and never on name. Two rows carrying the same address are
one teacher whose subjects are the union of both. Two teachers both called Mrs
Bello with different addresses are two teachers and must stay two: name
collisions are common in Nigerian schools, and merging on name would put one
person's classes under another person's record with nothing to show it had
happened.

Either shape is accepted, because a school will produce both. One row per
teacher with several subjects in the column, or one row per subject with the
teacher repeated. They resolve to the same thing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: How a school separates several subjects in one cell. Commas mostly, but a
#: slash, a semicolon and " and " all turn up, and a column split on commas
#: alone silently reads "Maths and Physics" as one subject nobody teaches.
SUBJECT_SEPARATORS = re.compile(r"\s*(?:,|;|/|\||\band\b|&)\s*", re.IGNORECASE)


def split_subjects(cell: str) -> list[str]:
    """The subjects in one cell, in the order the school wrote them."""

    parts = (part.strip() for part in SUBJECT_SEPARATORS.split(cell or ""))
    seen: dict[str, None] = {}
    for part in parts:
        if part:
            seen.setdefault(" ".join(part.split()), None)
    return list(seen)


@dataclass(slots=True)
class MergedTeacher:
    """One teacher, however many rows they arrived on."""

    email: str
    first_name: str
    last_name: str
    #: Union across every row carrying this address, first spelling kept.
    subjects: list[str] = field(default_factory=list)
    class_names: list[str] = field(default_factory=list)
    #: Every row this teacher came from, so a rejection can name the line.
    row_numbers: list[int] = field(default_factory=list)


def merge_rows(rows: list[tuple[int, dict[str, str]]]) -> list[MergedTeacher]:
    """Collapse teacher rows onto one record per email address.

    The first row to carry an address supplies the name. A later row with the
    same address and a different spelling does not overwrite it: there is no way
    to tell which spelling the school prefers, and picking the last one means
    the answer depends on row order.
    """

    merged: dict[str, MergedTeacher] = {}
    for row_number, values in rows:
        email = (values.get("email") or "").strip().casefold()
        if not email:
            # Rejected upstream, by row number. Nothing here can identify it.
            continue
        teacher = merged.get(email)
        if teacher is None:
            teacher = MergedTeacher(
                email=email,
                first_name=(values.get("first_name") or "").strip(),
                last_name=(values.get("last_name") or "").strip(),
            )
            merged[email] = teacher
        teacher.row_numbers.append(row_number)
        for subject in split_subjects(values.get("subjects") or ""):
            if subject not in teacher.subjects:
                teacher.subjects.append(subject)
        class_name = (values.get("class") or "").strip()
        if class_name and class_name not in teacher.class_names:
            teacher.class_names.append(class_name)
    return list(merged.values())
