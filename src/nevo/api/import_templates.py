"""The files a school downloads, generated from what the parser validates.

Three templates, all about to gain columns, and the reason this is backend work
is drift. If the front end holds the header row then the day a column changes
the template and the parser disagree, and a school downloads a file that its own
upload rejects - with nothing to notice it until a proprietor hits it during
onboarding. That already happened once: the drawn templates carried "Full name"
as one column and "Class(es)" with brackets, and the importer wanted first and
last separately and "class" singular.

So the headers come from the same tuples the parser checks against, and the test
beside this fails if a parser column has no template column or the reverse. That
test is the point of the ticket; everything else here is the file.
"""

from __future__ import annotations

import csv
import io
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Response
from sqlalchemy import select

from nevo.api.auth import PrincipalDependency
from nevo.api.dependencies import DatabaseSession
from nevo.api.onboarding import STUDENT_COLUMNS, TEACHER_COLUMNS
from nevo.api.product_common import require_school_actor
from nevo.db.models.account import Class, User
from nevo.db.models.subject import CanonicalSubject, SchoolSubject
from nevo.domain.accounts.vocabulary import UserRole

router = APIRouter(prefix="/api/v1", tags=["onboarding"])

ADMIN_ROLES = {UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}

TemplateName = Literal["students", "teachers", "classes"]

#: The class template has no import parser of its own yet - bulk class creation
#: is a JSON route - so its columns are stated here and the drift test holds
#: them against the bulk create request model instead.
CLASS_COLUMNS = ("name", "subjects")

#: Marked so plainly because a school will otherwise upload it as a real
#: record. It has happened on every product that shipped an example row
#: without one.
EXAMPLE_MARKER = "EXAMPLE ROW - DELETE THIS LINE BEFORE UPLOADING"

#: One format in the example, not four.
#:
#: The parser reads 2015-04-23, 23/04/2015, 23-04-2015 and 23 April 2015, which
#: is the right tolerance for a file a human typed. But a template that
#: demonstrates one format gets one format down the column, and a template that
#: demonstrates none gets a mixture.
EXAMPLE_DATE = "2015-04-23"

#: What a header looks like to a person. The parser folds case and turns spaces
#: into underscores, so "Date of birth" and "date_of_birth" are the same column
#: to it - and the readable one is what a school should see.
HEADINGS: dict[str, str] = {
    "first_name": "First name",
    "last_name": "Surname",
    "class": "Class",
    "date_of_birth": "Date of birth",
    "parent_first_name": "Parent first name",
    "parent_surname": "Parent surname",
    "parent_email": "Parent email",
    "email": "Email",
    "subjects": "Subjects",
    "name": "Class name",
}


def heading(column: str) -> str:
    return HEADINGS.get(column, column.replace("_", " ").capitalize())


def _csv(rows: list[list[str]]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer).writerows(rows)
    return buffer.getvalue()


def _download(name: str, body: str) -> Response:
    return Response(
        # BOM so Excel opens a UTF-8 file without mangling Nigerian names.
        content="﻿" + body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


async def _example_class_names(session: DatabaseSession, school_id: UUID | None) -> list[str]:
    """Class names the school already uses, for the example row.

    An example made of the school's own words is understood without
    instructions. An invented one gets copied literally, and then a school has
    a class called JSS 1A that it never taught.
    """

    rows = await session.scalars(
        select(Class.name)
        .where(Class.school_id == school_id, Class.archived_at.is_(None))
        .order_by(Class.name)
        .limit(2)
    )
    return list(rows)


async def _example_subjects(session: DatabaseSession, school_id: UUID | None) -> list[str]:
    """Subjects already on this school's list, for the same reason."""

    rows = await session.execute(
        select(SchoolSubject.name, CanonicalSubject.display_name)
        .outerjoin(CanonicalSubject, CanonicalSubject.id == SchoolSubject.canonical_subject_id)
        .where(SchoolSubject.school_id == school_id)
        .limit(2)
    )
    names = [canonical or own for own, canonical in rows]
    if names:
        return names
    # A school that has not added any yet gets two from Nevo's list rather than
    # an empty cell, which teaches nothing about the format.
    canonical = await session.scalars(
        select(CanonicalSubject.display_name).order_by(CanonicalSubject.display_name).limit(2)
    )
    return list(canonical)


@router.get("/onboarding/templates/{template}", response_class=Response)
async def download_template(
    template: TemplateName,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> Response:
    """The file for one template, with this school's own words in the example."""

    actor = await require_school_actor(session, principal, roles=ADMIN_ROLES)
    classes = await _example_class_names(session, actor.school_id)
    subjects = await _example_subjects(session, actor.school_id)
    first_class = classes[0] if classes else "JSS 1A"

    if template == "students":
        example = {
            "first_name": "Amara",
            "last_name": "Okafor",
            "class": first_class,
            "date_of_birth": EXAMPLE_DATE,
            "parent_first_name": "Ngozi",
            "parent_surname": "Okafor",
            "parent_email": "ngozi.okafor@example.com",
        }
        rows = [
            [heading(column) for column in STUDENT_COLUMNS],
            [example[column] for column in STUDENT_COLUMNS],
            [EXAMPLE_MARKER],
        ]
        return _download("nevo-student-roster.csv", _csv(rows))

    if template == "teachers":
        both = ", ".join(subjects) if len(subjects) > 1 else (subjects[0] if subjects else "")
        one = subjects[0] if subjects else ""
        second = subjects[1] if len(subjects) > 1 else one
        # Both accepted shapes shown, because either is valid and a school that
        # sees only one will assume the other is refused. Same email on the two
        # repeated rows: that is what merges them into one teacher.
        rows = [
            [heading(column) for column in TEACHER_COLUMNS],
            ["Bisi", "Bello", "bisi.bello@example.com", both, first_class],
            ["Chidi", "Eze", "chidi.eze@example.com", one, first_class],
            ["Chidi", "Eze", "chidi.eze@example.com", second, first_class],
            [EXAMPLE_MARKER + " - all three"],
        ]
        return _download("nevo-teacher-import.csv", _csv(rows))

    rows = [
        [heading(column) for column in CLASS_COLUMNS],
        [first_class, ", ".join(subjects)],
        [EXAMPLE_MARKER],
    ]
    return _download("nevo-class-import.csv", _csv(rows))


__all__ = ["CLASS_COLUMNS", "EXAMPLE_DATE", "EXAMPLE_MARKER", "User", "heading", "router"]
