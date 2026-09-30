"""Turning teacher rows from a spreadsheet into teachers and their assignments.

Two rules do the work, and both are about not fusing things that are not one
thing.

**Rows merge on email and never on name.** Two rows carrying the same address
are one teacher. Two teachers both called Mrs Bello with different addresses
are two teachers and must stay two: name collisions are common in Nigerian
schools, and merging on name would file one person's classes under another
person's record with nothing to show it had happened.

**One row is one assignment.** A teacher taking three class-and-subject
combinations appears on three rows, and the three merge into one teacher
holding three assignments. The tempting alternative - one row with a list of
subjects and a list of classes - cross multiplies wrongly: subjects
"Maths; Further Maths" against classes "JSS 2A; SS1" produces four pairs, two
of which nobody teaches. That is why the pair travels together on its own row
and is never reassembled from two lists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: How a school separates several values in one cell, where a legacy file still
#: does.
#:
#: Semicolons, not commas. A comma inside a cell breaks the file for anyone
#: editing it in Excel, which is everyone, so the template has never asked for
#: one. This exists only so an older file is read rather than refused.
LEGACY_SEPARATORS = re.compile(r"\s*[;|/]\s*")


def split_legacy(cell: str) -> list[str]:
    """The values in one cell, for a file that predates row-per-assignment.

    Row-per-assignment needs none of this: one row carries one subject. It is
    kept because a school will upload last term's file, and reading it is
    better than rejecting it.
    """

    seen: dict[str, None] = {}
    for part in LEGACY_SEPARATORS.split(cell or ""):
        cleaned = " ".join(part.split())
        if cleaned:
            seen.setdefault(cleaned, None)
    return list(seen)


@dataclass(frozen=True, slots=True)
class Assignment:
    """One thing a teacher teaches: a subject, to a class.

    The pair, together. Splitting it into two lists is the cross-multiplication
    this module exists to avoid.
    """

    subject: str
    class_name: str


@dataclass(slots=True)
class MergedTeacher:
    """One teacher, however many rows they arrived on."""

    email: str
    first_name: str
    last_name: str
    #: Every subject-and-class pair this person teaches, in file order.
    assignments: list[Assignment] = field(default_factory=list)
    #: Every row this teacher came from, so a rejection can name the line.
    row_numbers: list[int] = field(default_factory=list)

    @property
    def subjects(self) -> list[str]:
        """The distinct subjects across their assignments, first spelling kept.

        Derived rather than stored, so it cannot drift from the assignments it
        is meant to describe.
        """

        seen: dict[str, None] = {}
        for assignment in self.assignments:
            seen.setdefault(assignment.subject, None)
        return list(seen)

    @property
    def class_names(self) -> list[str]:
        seen: dict[str, None] = {}
        for assignment in self.assignments:
            seen.setdefault(assignment.class_name, None)
        return list(seen)


def merge_rows(rows: list[tuple[int, dict[str, str]]]) -> list[MergedTeacher]:
    """Collapse teacher rows onto one record per email address.

    The first row to carry an address supplies the name. A later row with the
    same address and a different spelling does not overwrite it: there is no
    way to tell which spelling the school prefers, and taking the last one
    makes the answer depend on row order.
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
        for assignment in _assignments_on(values):
            if assignment not in teacher.assignments:
                teacher.assignments.append(assignment)
    return list(merged.values())


def _assignments_on(values: dict[str, str]) -> list[Assignment]:
    """The pairs one row carries. Normally exactly one.

    A legacy row holding several subjects in the cell is expanded against that
    row's own class, which is safe: the class on the row is the class those
    subjects are taught to. It is pairing across two multi-valued cells that
    invents assignments, and no row here has two.
    """

    class_name = " ".join((values.get("class") or "").split())
    if not class_name:
        return []
    return [
        Assignment(subject=subject, class_name=class_name)
        for subject in split_legacy(values.get("subject") or "")
    ]
