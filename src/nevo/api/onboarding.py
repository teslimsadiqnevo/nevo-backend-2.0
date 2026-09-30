"""Upload, derive, confirm, pay, activate - in that order.

A school could create classes, add teachers and add students without paying
anything. The product was fully usable before money changed hands, which is a
revenue hole rather than a design gap.

So an upload now proposes rather than creates. Nevo reads the class names out
of whichever file arrives first and offers the list back; the school corrects
it; only then do classes and people exist, and only after the invoice is paid
does anyone hear from Nevo. The last step is refused by the server, not by a
hidden button, because a button is not a gate.
"""

from __future__ import annotations

import csv
import io
import secrets
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.api.auth import PrincipalDependency
from nevo.api.casing import CAMEL_CONFIG
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_common import require_school_actor
from nevo.api.response_models import CamelResponse
from nevo.billing.entities import PerStudentQuote
from nevo.billing.issuance import TERM_DATES_KEY
from nevo.billing.service import quote_per_student
from nevo.db.models.account import Class, School, StudentClassEnrollment, User
from nevo.db.models.billing import Invoice
from nevo.db.models.onboarding import OnboardingRow, SchoolOnboarding
from nevo.db.models.subject import ClassSubject, TeacherSubject
from nevo.db.models.teacher_assignment import TeacherClassAssignment
from nevo.domain.accounts.classes import academic_session, normalise_class_name, parse_class_name
from nevo.domain.accounts.vocabulary import AuthMethod, UserRole, UserStatus
from nevo.domain.billing.vocabulary import InvoiceStatus, RateType
from nevo.domain.onboarding.vocabulary import OnboardingRowKind, OnboardingStage
from nevo.domain.teacher_assignments.vocabulary import (
    TeacherAssignmentRole,
    TeacherAssignmentSource,
)
from nevo.subjects.resolution import ensure
from nevo.subjects.teacher_import import merge_rows

router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])

ADMIN_ROLES = {"senco_admin", "other_admin"}

#: A school file is a spreadsheet exported as CSV. Anything larger than this
#: is not a school's roster, and reading it into memory would be a way to take
#: the API down from a file upload.
MAX_UPLOAD_BYTES = 2_000_000

#: The student roster, final columns. SCRUM-203.
#:
#: The guardian's contact is required and their name is not: the parent supplies
#: their own at account setup, so a school pre-filling it is a convenience. A
#: proprietor should not have to go and find a parent's full name before a child
#: can be enrolled.
STUDENT_COLUMNS = (
    "first_name",
    "last_name",
    "class",
    "date_of_birth",
    "admission_number",
    "guardian_first_name",
    "guardian_last_name",
    "guardian_email",
    "guardian_relationship",
)

#: Columns a student row must actually carry a value in, and why each one
#: blocks rather than warns:
#:
#: No class and the child has nowhere to go. No date of birth and age cannot be
#: derived, which SCRUM-168 needs. No admission number and the child cannot
#: identify themselves at the door or be matched on a re-upload. No guardian
#: email and consent cannot be requested, so the child can never be activated.
REQUIRED_STUDENT_COLUMNS = (
    "first_name",
    "last_name",
    "class",
    "date_of_birth",
    "admission_number",
    "guardian_email",
)

#: The teacher roster, final columns. One row per thing a teacher teaches.
#:
#: A teacher taking three class-and-subject combinations appears three times,
#: and those three rows merge into one teacher holding three assignments. The
#: alternative - one row with a list of subjects and a list of classes - cross
#: multiplies wrongly: "Maths; Further Maths" against "JSS 2A; SS1" would
#: assign Further Maths to JSS 2A and Maths to SS1, neither of which she
#: teaches.
TEACHER_COLUMNS = ("first_name", "last_name", "email", "subject", "class")

#: All of them. A row missing the subject or the class is not an assignment,
#: and a row without an email cannot be attached to a person at all.
REQUIRED_TEACHER_COLUMNS = TEACHER_COLUMNS

#: Teachers are free; students are what a school pays for. Adding a teacher
#: after activation therefore costs nothing and adding a student does.
BILLABLE_KIND = OnboardingRowKind.STUDENT


class RejectedRow(CamelResponse):
    """Why one line of the file cannot be used, in terms of that line."""

    row_number: int
    field: str
    value: str
    reason: str


class DerivedClass(CamelResponse):
    """A class Nevo found in the file, with what it found in it."""

    name: str
    normalised_name: str
    year_group: str | None
    section: str | None
    student_count: int
    teacher_count: int
    #: True once this class exists as a row rather than as a proposal.
    committed: bool = False


class OnboardingState(CamelResponse):
    """Everything the onboarding screens render, in one read."""

    stage: OnboardingStage
    classes: list[DerivedClass]
    teacher_count: int
    student_count: int
    rejected: list[RejectedRow]
    #: Null until the headcount is confirmed and priced.
    invoice_id: UUID | None = None
    amount_due: Decimal | None = None
    currency: str | None = None
    period_label: str | None = None
    #: What the school can do next, decided here rather than inferred by the
    #: console from which lists are empty.
    can_confirm: bool = False
    can_pay: bool = False
    can_activate: bool = False
    #: Whether this school is partway through onboarding and its console
    #: should be held read-only.
    #:
    #: False for a school that never came through the funnel at all - every
    #: school that existed before it was built, and any opened by hand. The
    #: stage of such a school reads as activated, which is the true answer to
    #: "where is this school between uploading a file and opening its
    #: workspace": open. Branch on this, not on the stage, and never on the
    #: absence of a record - this route does not 404.
    in_onboarding: bool = False


class ClassCorrection(BaseModel):
    """One edit a school makes on the confirmation screen."""

    model_config = CAMEL_CONFIG

    normalised_name: Annotated[str, Field(min_length=1, max_length=255)]
    #: A new name merges this class into whatever it is renamed to, which is
    #: how a typo is corrected rather than by deleting and re-uploading.
    rename_to: Annotated[str | None, Field(default=None, max_length=255)] = None
    #: Dropping a class drops the rows in it. A school with a leavers' class
    #: in its file should not pay for it.
    drop: bool = False


class ClassCorrections(BaseModel):
    model_config = CAMEL_CONFIG

    corrections: Annotated[list[ClassCorrection], Field(min_length=1, max_length=200)]


class AdditionQuoteRequest(BaseModel):
    model_config = CAMEL_CONFIG

    students: Annotated[int, Field(ge=0, le=5000)] = 0
    teachers: Annotated[int, Field(ge=0, le=500)] = 0


class AdditionQuote(CamelResponse):
    """What adding people costs, broken out the way an invoice is.

    It used to carry one ``amount`` with no description, so a client could not
    tell whether VAT was in it - and a screen that shows a rate, a VAT line
    and a total had to do the arithmetic itself, which is exactly what
    PricingResponse exists to prevent. The same four fields are here now, from
    the same pricing function, already rounded.
    """

    students: int
    teachers: int
    per_student_rate: Decimal
    amount: Decimal = Field(
        description=(
            "Equal to totalWithVat. Retained because it was the only total "
            "here, and it said nothing about VAT - prefer the named fields."
        )
    )
    total_before_vat: Decimal
    vat_rate: Decimal = Field(
        description=(
            "VAT as a percentage, not a fraction: Nigeria's 7.5% is sent as "
            '"7.50". Render it with a per-cent sign and do not multiply by 100.'
        ),
        examples=[Decimal("7.50")],
    )
    vat_amount: Decimal
    total_with_vat: Decimal
    currency: str
    #: Which term this price is for, written the way the rest of the product
    #: writes a school year: "Term 2 · 2026/2027". The year is in full, the
    #: same as a class's academicSession, so the two never disagree on screen.
    #: Null where the school has not configured its term dates, in which case
    #: there is no term to name and the screen should not invent one.
    applies_to: str | None = None
    #: What actually happens to this money, because nothing charges it yet.
    #: See ``billed`` on the quote route.
    billed: Literal["next_invoice"] = "next_invoice"
    #: Said plainly because a school asks: a teacher account is free.
    message: str


def _quote(school: School, student_count: int) -> PerStudentQuote:
    """Price a headcount the way an invoice run does.

    The same function the scheduled billing uses, so what a school is quoted
    at onboarding and what it is billed later cannot drift apart.
    """

    return quote_per_student(
        plan=school.pricing_plan,
        student_count=student_count,
        rate_type=(RateType.FOUNDING_PARTNER if school.is_founding_partner else RateType.STANDARD),
        per_student_rate=school.per_student_rate,
        rate_locked_until=school.price_lock_expiry,
    )


async def _already_running(session: AsyncSession, school_id: UUID | None) -> bool:
    """Whether this school has children learning already.

    The one signal that separates a school partway through setup from one that
    has been open for months: during the funnel nobody is active until
    activation, and after it everybody is.
    """

    active = await session.scalar(
        select(func.count(User.id)).where(
            User.school_id == school_id,
            User.role == UserRole.STUDENT,
            User.status == UserStatus.ACTIVE,
        )
    )
    return bool(active)


async def _onboarding(session: AsyncSession, school_id: UUID | None) -> SchoolOnboarding:
    record = await session.scalar(
        select(SchoolOnboarding).where(SchoolOnboarding.school_id == school_id)
    )
    if record is None:
        record = SchoolOnboarding(school_id=school_id)
        session.add(record)
        await session.flush()
    return record


async def _rows(session: AsyncSession, onboarding_id: UUID) -> list[OnboardingRow]:
    rows = await session.scalars(
        select(OnboardingRow)
        .where(OnboardingRow.onboarding_id == onboarding_id)
        .order_by(OnboardingRow.kind, OnboardingRow.row_number)
    )
    return list(rows)


def _derived_classes(rows: list[OnboardingRow]) -> list[DerivedClass]:
    found: dict[str, DerivedClass] = {}
    for row in rows:
        if not row.countable or not row.normalised_class_name or row.class_name is None:
            continue
        parsed = parse_class_name(row.class_name)
        derived = found.get(row.normalised_class_name)
        if derived is None:
            derived = DerivedClass(
                name=parsed.name,
                normalised_name=row.normalised_class_name,
                year_group=parsed.year_group,
                section=parsed.section,
                student_count=0,
                teacher_count=0,
            )
            found[row.normalised_class_name] = derived
        if row.kind is OnboardingRowKind.STUDENT:
            derived.student_count += 1
        else:
            derived.teacher_count += 1
    return sorted(found.values(), key=lambda item: item.normalised_name)


def _state(
    record: SchoolOnboarding,
    rows: list[OnboardingRow],
    invoice: Invoice | None,
) -> OnboardingState:
    classes = _derived_classes(rows)
    students = sum(1 for row in rows if row.countable and row.kind is OnboardingRowKind.STUDENT)
    teachers = sum(1 for row in rows if row.countable and row.kind is OnboardingRowKind.TEACHER)
    paid = invoice is not None and invoice.status is InvoiceStatus.PAID
    return OnboardingState(
        stage=record.stage,
        classes=classes,
        teacher_count=teachers,
        student_count=students,
        rejected=[
            RejectedRow(
                row_number=row.row_number,
                field=row.rejection_field or "",
                value=row.rejection_value or "",
                reason=row.rejection_reason or "",
            )
            for row in rows
            if row.rejected
        ],
        invoice_id=invoice.id if invoice else None,
        amount_due=invoice.amount if invoice else None,
        currency=invoice.currency.value if invoice else None,
        period_label=invoice.period_label if invoice else None,
        can_confirm=record.stage is OnboardingStage.UPLOADING and students > 0,
        can_pay=record.stage is OnboardingStage.AWAITING_PAYMENT and not paid,
        can_activate=record.stage is OnboardingStage.AWAITING_PAYMENT and paid,
    )


async def _invoice(session: AsyncSession, record: SchoolOnboarding) -> Invoice | None:
    if record.invoice_id is None:
        return None
    return await session.get(Invoice, record.invoice_id)


async def _state_for(session: AsyncSession, record: SchoolOnboarding) -> OnboardingState:
    return _state(record, await _rows(session, record.id), await _invoice(session, record))


def _read_rows(raw: bytes, kind: OnboardingRowKind) -> list[OnboardingRow]:
    """Turn an uploaded file into rows, keeping every line it could not use.

    A count of failures is not enough: a school uploading four hundred
    children will not notice thirty missing, so each rejection carries its
    line, its field, the value that caused it and a sentence to act on.
    """

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "unreadable_file",
                "message": (
                    "Save the file as CSV from your spreadsheet and upload it "
                    "again. This one is not text Nevo can read."
                ),
            },
        ) from error
    reader = csv.DictReader(io.StringIO(text))
    headers = {_column(name) for name in (reader.fieldnames or [])}
    # Only the columns whose values are required. A column the template offers
    # but does not insist on - a guardian's name, the relationship - is
    # optional as a header too, so last term's copy of the template still
    # imports. Refusing a file for a header we ourselves made optional is the
    # drift SCRUM-199 exists to prevent, arriving from the other direction.
    missing = [column for column in _required(kind) if column not in headers]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "missing_columns",
                "message": (
                    "This file is missing "
                    + ", ".join(column.replace("_", " ") for column in missing)
                    + ". Download the template and upload it again."
                ),
                "missingColumns": missing,
            },
        )
    rows: list[OnboardingRow] = []
    for number, raw_row in enumerate(reader, start=2):  # row 1 is the header
        values = {_column(key): (value or "").strip() for key, value in raw_row.items() if key}
        row = OnboardingRow(kind=kind, row_number=number, values=values)
        class_name = values.get("class", "")
        if class_name:
            row.class_name = parse_class_name(class_name).name
            row.normalised_class_name = normalise_class_name(class_name)
        _reject_incomplete(row, values, _required(kind))
        rows.append(row)
    _reject_duplicate_admission_numbers(rows)
    return rows


def _reject_duplicate_admission_numbers(rows: list[OnboardingRow]) -> None:
    """Two children sharing an identity is the same failure as none. SCRUM-203.

    The admission number is how a child identifies themselves at the door and
    how a re-upload is matched to the right row. Two rows carrying one number
    means one of those children signs in as the other, so the later row is
    refused and named rather than quietly overwriting the earlier one.
    """

    seen: dict[str, int] = {}
    for row in rows:
        if row.kind is not OnboardingRowKind.STUDENT or row.rejected:
            continue
        raw = (row.values or {}).get("admission_number", "")
        number = " ".join(str(raw).split()).casefold()
        if not number:
            continue
        first = seen.get(number)
        if first is None:
            seen[number] = row.row_number
            continue
        row.rejected = True
        row.rejection_field = "admission_number"
        row.rejection_value = str((row.values or {}).get("admission_number", ""))
        row.rejection_reason = (
            f"Row {row.row_number} has the same admission number as row {first}. "
            "Two children cannot share one, because it is how each of them "
            "signs in. Give this row its own number, or take it out."
        )


def _required(kind: OnboardingRowKind) -> tuple[str, ...]:
    """Which of the columns a row must actually fill in.

    Separate from the header list: a column can be part of the template, and
    so required to be present, without every row having to carry a value.
    Parent name is exactly that.
    """

    if kind is OnboardingRowKind.STUDENT:
        return REQUIRED_STUDENT_COLUMNS
    return REQUIRED_TEACHER_COLUMNS


def _reject_incomplete(
    row: OnboardingRow,
    values: dict[str, str],
    wanted: tuple[str, ...],
) -> None:
    for column in wanted:
        if values.get(column):
            continue
        row.rejected = True
        row.rejection_field = column
        row.rejection_value = values.get(column, "")
        row.rejection_reason = (
            f"Row {row.row_number} has no {column.replace('_', ' ')}. "
            "Add it to the file, or take the row out before uploading."
        )
        return
    born = values.get("date_of_birth", "")
    if born and _parse_date(born) is None:
        row.rejected = True
        row.rejection_field = "date_of_birth"
        row.rejection_value = born
        # Never resolved by asking the child afterwards, which is the whole
        # point of taking it from the roster.
        row.rejection_reason = (
            f"{born} is not a date Nevo can read. Write it as 2015-04-23, and "
            "take it from the school's own record rather than asking the child."
        )
        return
    email = values.get("parent_email") or values.get("email") or ""
    if email and "@" not in email:
        row.rejected = True
        row.rejection_field = "parent_email" if "parent_email" in values else "email"
        row.rejection_value = email
        row.rejection_reason = f"{email} is not an email address."


def _parse_date(value: str) -> date | None:
    """Read a date a school wrote, in the orders a school writes them."""

    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(value.strip(), pattern).date()
        except ValueError:
            continue
    return None


#: Words a school writes for a column we call something else.
#:
#: Tolerance in the same spirit as reading four date formats: a file that says
#: "Surname" is not a malformed file. This list is also what makes the
#: generated templates importable, since the readable heading has to fold back
#: to the column the parser wants - a round trip the template test asserts.
#:
#: The guardian_* aliases matter for a different reason. Schools keep old
#: copies of the template, and the columns were called parent_* until
#: SCRUM-203. A file downloaded last week still imports.
COLUMN_ALIASES = {
    "surname": "last_name",
    "family_name": "last_name",
    "other_names": "first_name",
    "given_name": "first_name",
    "given_names": "first_name",
    "forename": "first_name",
    "dob": "date_of_birth",
    "date_of_birth_yyyy_mm_dd": "date_of_birth",
    "class_name": "name",
    "classes": "class",
    # What the drawn template actually says. Punctuation is stripped to a
    # space, so "Class(es)" arrives here as class_es.
    "class_es": "class",
    "subjects": "subject",
    "e_mail": "email",
    "email_address": "email",
    # The child's own identifier. Always read to a person as
    # "Student ID / Admission Number", so both halves resolve.
    "student_id": "admission_number",
    "student_id_admission_number": "admission_number",
    "admission_no": "admission_number",
    "admission": "admission_number",
    # Older templates, before the guardian rename.
    "parent_first_name": "guardian_first_name",
    "parent_surname": "guardian_last_name",
    "parent_last_name": "guardian_last_name",
    "parent_name": "guardian_first_name",
    "guardian_name": "guardian_first_name",
    "guardian_surname": "guardian_last_name",
    "parent_email": "guardian_email",
    "guardian_e_mail": "guardian_email",
    "parent_relationship": "guardian_relationship",
    "relationship": "guardian_relationship",
    # The readable heading on the generated template. It has to fold back to
    # the column the parser wants, which is the round trip the template test
    # asserts - and the reason that test exists.
    "relationship_to_the_child": "guardian_relationship",
}

#: Columns a file may still carry that Nevo no longer wants.
#:
#: Ignored rather than rejected. guardian_phone was struck when parent contact
#: became email only, and a school holding last term's template should not be
#: turned away over a column we asked for ourselves.
RETIRED_COLUMNS = frozenset({"guardian_phone", "parent_phone", "phone", "parent_contact"})


def _column(name: str) -> str:
    folded = name.strip().casefold()
    # Punctuation a spreadsheet picks up: "Class (es)", "E-mail", "D.O.B".
    for character in "().-/":
        folded = folded.replace(character, " ")
    folded = "_".join(folded.split())
    return COLUMN_ALIASES.get(folded, folded)


@router.get("", response_model=OnboardingState)
async def read_onboarding(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> OnboardingState:
    """Where this school is, if it is anywhere.

    Reading does not start an onboarding. It used to: the helper this shared
    with the write routes creates a record when it finds none, so the first
    admin page load at a school that predates the funnel wrote a row saying
    that school was back at "uploading" - and every console reading the stage
    would then have held an established school read-only. A read that changes
    the answer to itself is the bug; this one only looks.
    """

    actor = await require_school_actor(session, principal, roles=ADMIN_ROLES)
    record = await session.scalar(
        select(SchoolOnboarding).where(SchoolOnboarding.school_id == actor.school_id)
    )
    if record is None:
        return OnboardingState(
            stage=OnboardingStage.ACTIVATED,
            classes=[],
            teacher_count=0,
            student_count=0,
            rejected=[],
            in_onboarding=False,
        )
    state = await _state_for(session, record)
    state = state.model_copy(
        update={"in_onboarding": record.stage is not OnboardingStage.ACTIVATED}
    )
    await session.commit()
    return state


@router.post("/imports", response_model=OnboardingState)
async def stage_import(
    principal: PrincipalDependency,
    session: DatabaseSession,
    kind: Annotated[Literal["teacher", "student"], Form()],
    file: Annotated[UploadFile, File()],
) -> OnboardingState:
    """Read a file and propose what is in it. Nothing is created here.

    Re-uploading replaces the previous file of the same kind, because a school
    correcting its spreadsheet and uploading again means the new one.
    """

    actor = await require_school_actor(session, principal, roles=ADMIN_ROLES)
    if await _already_running(session, actor.school_id):
        # A school that predates this funnel has no onboarding record, and the
        # helper below creates one when it finds none - so without this guard
        # an established school could start the funnel from scratch, confirm
        # its whole roster and be invoiced a second time for children it is
        # already paying for. The stage check underneath cannot catch it,
        # because a fresh record's stage is exactly the one it allows.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "school_already_active",
                "message": (
                    "This school is already running. Add people from the admin "
                    "console rather than through setup, so nobody is billed "
                    "twice for the same child."
                ),
            },
        )
    record = await _onboarding(session, actor.school_id)
    if record.stage is not OnboardingStage.UPLOADING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "onboarding_already_confirmed",
                "message": (
                    "This school's roster has already been confirmed. Add "
                    "people from the admin console instead."
                ),
            },
        )
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": "file_too_large",
                "message": (
                    "That file is larger than a school roster. Check you picked the right one."
                ),
            },
        )
    row_kind = OnboardingRowKind(kind)
    for existing in await _rows(session, record.id):
        if existing.kind is row_kind:
            await session.delete(existing)
    for row in _read_rows(raw, row_kind):
        row.onboarding_id = record.id
        session.add(row)
    await session.flush()
    state = await _state_for(session, record)
    await session.commit()
    return state


@router.patch("/classes", response_model=OnboardingState)
async def correct_derived_classes(
    payload: ClassCorrections,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> OnboardingState:
    """Rename or drop a class Nevo derived, before anything is committed.

    This is what protects a school from a typo becoming a phantom class, and
    it protects better than refusing the row did, because the school is
    looking at the whole list when it decides.
    """

    actor = await require_school_actor(session, principal, roles=ADMIN_ROLES)
    record = await _onboarding(session, actor.school_id)
    if record.stage is not OnboardingStage.UPLOADING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "onboarding_already_confirmed",
                "message": "The roster is confirmed. Change classes in the admin console.",
            },
        )
    rows = await _rows(session, record.id)
    for correction in payload.corrections:
        wanted = normalise_class_name(correction.normalised_name)
        for row in rows:
            if row.normalised_class_name != wanted:
                continue
            if correction.drop:
                row.excluded = True
            elif correction.rename_to:
                row.class_name = parse_class_name(correction.rename_to).name
                row.normalised_class_name = normalise_class_name(correction.rename_to)
    await session.flush()
    state = await _state_for(session, record)
    await session.commit()
    return state


@router.post("/confirm", response_model=OnboardingState)
async def confirm_and_price(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> OnboardingState:
    """Commit the derived classes, hold the people, and raise the invoice.

    Classes become rows here because a school needs to see its own structure
    while it decides to pay. People do not: an account that exists before
    payment is the hole this ticket closes.
    """

    actor = await require_school_actor(session, principal, roles=ADMIN_ROLES)
    record = await _onboarding(session, actor.school_id)
    rows = await _rows(session, record.id)
    students = [row for row in rows if row.countable and row.kind is OnboardingRowKind.STUDENT]
    if record.stage is not OnboardingStage.UPLOADING:
        return await _state_for(session, record)
    if not students:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "nothing_to_confirm",
                "message": "Upload a student file before confirming. Nevo is priced per student.",
            },
        )
    school = await session.get(School, actor.school_id)
    assert school is not None
    session_label = academic_session(datetime.now(UTC).date())
    await _commit_classes(session, school, rows, session_label)
    quote = _quote(school, len(students))
    invoice = Invoice(
        invoice_number=f"NEVO-ONB-{secrets.token_hex(4).upper()}",
        school_id=school.id,
        issued_at=date.today(),
        amount=quote.total_with_vat,
        status=InvoiceStatus.PENDING,
        due_at=date.today() + timedelta(days=14),
        pdf_url="",
        student_count=quote.student_count,
        per_student_rate=quote.per_student_rate,
        total_before_vat=quote.total_before_vat,
        vat_amount=quote.vat_amount,
        vat_rate=quote.vat_rate,
        period_label=f"Onboarding, {session_label}",
    )
    session.add(invoice)
    await session.flush()
    record.invoice_id = invoice.id
    record.confirmed_at = datetime.now(UTC)
    record.stage = OnboardingStage.AWAITING_PAYMENT
    await session.flush()
    state = await _state_for(session, record)
    await session.commit()
    return state


async def _commit_classes(
    session: AsyncSession,
    school: School,
    rows: list[OnboardingRow],
    session_label: str,
) -> dict[str, Class]:
    """Create the derived classes the school kept, and find the ones it has."""

    existing = {
        item.normalised_name: item
        for item in await session.scalars(
            select(Class).where(
                Class.school_id == school.id,
                Class.academic_session == session_label,
                Class.archived_at.is_(None),
            )
        )
    }
    for derived in _derived_classes(rows):
        if derived.normalised_name in existing:
            continue
        row = Class(
            school_id=school.id,
            name=derived.name,
            year_group=derived.year_group,
            section=derived.section,
            academic_session=session_label,
            class_code=secrets.token_hex(3).upper(),
            source="import",
        )
        session.add(row)
        await session.flush()
        existing[derived.normalised_name] = row
    return existing


@router.post("/activate", response_model=OnboardingState)
async def activate(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> OnboardingState:
    """Create the accounts, once the invoice is paid and not before.

    Refused here rather than by hiding the button, because a hidden button is
    not a gate: this is the line between a school that has paid and one that
    has not.
    """

    actor = await require_school_actor(session, principal, roles=ADMIN_ROLES)
    record = await _onboarding(session, actor.school_id)
    if record.stage is OnboardingStage.ACTIVATED:
        return await _state_for(session, record)
    invoice = await _invoice(session, record)
    if invoice is None or invoice.status is not InvoiceStatus.PAID:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "payment_outstanding",
                "message": (
                    "Nothing has been sent to your teachers or parents yet. "
                    "Once this invoice is paid, accounts are created and the "
                    "invitations go out."
                ),
                "invoiceId": str(invoice.id) if invoice else None,
            },
        )
    school = await session.get(School, actor.school_id)
    assert school is not None
    rows = await _rows(session, record.id)
    session_label = academic_session(datetime.now(UTC).date())
    classes = await _commit_classes(session, school, rows, session_label)
    for row in rows:
        if not row.countable:
            continue
        await _create_person(session, school, row, classes)
    await session.flush()
    # Subjects after the accounts exist, because a teacher's subject list hangs
    # off their user row. Merged on email across every row that carried it, so
    # a school that wrote one row per subject gets one teacher with several and
    # not several teachers with one each. SCRUM-194.
    await _attach_teacher_subjects(session, school, rows, classes)
    record.activated_at = datetime.now(UTC)
    record.stage = OnboardingStage.ACTIVATED
    await session.flush()
    state = await _state_for(session, record)
    await session.commit()
    return state


async def _attach_teacher_subjects(
    session: AsyncSession,
    school: School,
    rows: list[OnboardingRow],
    classes: dict[str, Class],
) -> None:
    """Derive subjects and assignments from the teacher file. SCRUM-203.

    Three things fall out of one pass, and none of them is typed by a school:

    The teacher's own subject list, which is what that person teaches. Each
    class's subject list, which is every subject taught to that class - this
    closes the hole where a derived class arrived with no subjects at all,
    leaving its teachers unassignable and its students with no subjects. And
    the assignment itself, which is a teacher, a subject and a class.

    Merged on email and never on name: two teachers both called Mrs Bello with
    different addresses are two teachers, and fusing them would file one
    person's classes under the other with nothing to show it happened.
    """

    teacher_rows = [
        (row.row_number, {str(k): str(v) for k, v in (row.values or {}).items()})
        for row in rows
        if row.countable and row.kind is OnboardingRowKind.TEACHER
    ]
    if not teacher_rows:
        return
    now = datetime.now(UTC)
    for merged in merge_rows(teacher_rows):
        teacher = await session.scalar(
            select(User).where(
                User.school_id == school.id,
                func.lower(User.email) == merged.email,
            )
        )
        if teacher is None:
            continue
        for assignment in merged.assignments:
            subject = await ensure(session, school_id=school.id, typed=assignment.subject)
            await _hold(
                session,
                TeacherSubject,
                teacher_id=teacher.id,
                school_subject_id=subject.id,
            )
            school_class = classes.get(normalise_class_name(assignment.class_name))
            if school_class is None:
                # A class named in the teacher file that the student file never
                # mentioned. The teacher keeps the subject; there is no class to
                # attach it to, and inventing one would put a class on the
                # invoice that has no children in it.
                continue
            await _hold(
                session, ClassSubject, class_id=school_class.id, school_subject_id=subject.id
            )
            existing = await session.scalar(
                select(TeacherClassAssignment.id).where(
                    TeacherClassAssignment.teacher_id == teacher.id,
                    TeacherClassAssignment.class_id == school_class.id,
                    TeacherClassAssignment.school_subject_id == subject.id,
                    TeacherClassAssignment.removed_at.is_(None),
                )
            )
            if existing is None:
                session.add(
                    TeacherClassAssignment(
                        school_id=school.id,
                        teacher_id=teacher.id,
                        class_id=school_class.id,
                        school_subject_id=subject.id,
                        # Not primary. One class may have only one primary
                        # teacher, and the roster describes who teaches which
                        # subject rather than who holds the form - so every
                        # derived assignment being primary would refuse the
                        # second subject teacher of every class.
                        role=TeacherAssignmentRole.CO_TEACHER,
                        source=TeacherAssignmentSource.ROSTER_SYNC,
                        assigned_at=now,
                    )
                )
    await session.flush()


async def _hold(
    session: AsyncSession,
    model: type[ClassSubject] | type[TeacherSubject],
    **keys: object,
) -> None:
    """Add a join row unless it is already there."""

    columns = [getattr(model, name) == value for name, value in keys.items()]
    found = await session.scalar(select(model.id).where(*columns))
    if found is None:
        session.add(model(**keys))


async def _create_person(
    session: AsyncSession,
    school: School,
    row: OnboardingRow,
    classes: dict[str, Class],
) -> None:
    """One roster row becomes one account.

    Students arrive active: their parent still has to consent before they can
    learn, and that gate is the consent record's, not this one's. Teachers
    arrive invited, because an invitation is how a teacher sets a password.
    """

    values = {str(key): str(value) for key, value in row.values.items()}
    first_name = values.get("first_name", "").strip()
    last_name = values.get("last_name", "").strip() or None
    is_student = row.kind is OnboardingRowKind.STUDENT
    admission_number = (values.get("admission_number") or "").strip() or None
    user = None
    if is_student and admission_number is not None:
        # The admission number is the school's own name for the child, so a
        # second roster carrying it is the same child again and not a new one.
        # Merging keeps their history instead of stranding it behind a
        # duplicate account - and the school's unique index would refuse the
        # insert anyway. SCRUM-202.
        user = await session.scalar(
            select(User).where(
                User.school_id == school.id,
                User.role == UserRole.STUDENT,
                func.lower(User.admission_number) == admission_number.lower(),
            )
        )
    if user is not None:
        user.first_name = first_name or user.first_name
        user.last_name = last_name or user.last_name
        user.date_of_birth = _parse_date(values.get("date_of_birth", "")) or user.date_of_birth
    else:
        user = User(
            school_id=school.id,
            role=UserRole.STUDENT if is_student else UserRole.TEACHER,
            date_of_birth=_parse_date(values.get("date_of_birth", "")) if is_student else None,
            auth_method=AuthMethod.EMAIL_PASSWORD,
            first_name=first_name,
            last_name=last_name,
            email=(values.get("email") or "").casefold() or None,
            admission_number=admission_number if is_student else None,
            status=UserStatus.ACTIVE if is_student else UserStatus.INVITED,
        )
        session.add(user)
    await session.flush()
    school_class = classes.get(row.normalised_class_name or "")
    if is_student and school_class is not None:
        await _hold_enrollment(session, user.id, school_class.id)


async def _hold_enrollment(session: AsyncSession, student_id: UUID, class_id: UUID) -> None:
    """Enrol a child in a class unless they are already in it."""

    found = await session.scalar(
        select(StudentClassEnrollment.id).where(
            StudentClassEnrollment.student_id == student_id,
            StudentClassEnrollment.class_id == class_id,
        )
    )
    if found is None:
        session.add(StudentClassEnrollment(student_id=student_id, class_id=class_id))


#: How a school writes the term a price belongs to.
TERM_LABEL = "Term {term} \u00b7 {session}"


def _current_term_label(school: School, today: date | None = None) -> str | None:
    """Which term we are in, named the way a school names it.

    From the school's own term start dates, which is the only place that
    knowledge lives. A school that has not configured them has no term to
    name, and returning None is better than guessing at somebody's calendar
    and printing it on a price.
    """

    raw = school.academic_config.get(TERM_DATES_KEY)
    if not isinstance(raw, list) or not raw:
        return None
    starts: list[date] = []
    for item in raw:
        try:
            starts.append(date.fromisoformat(str(item)))
        except ValueError:
            return None
    on = today or datetime.now(UTC).date()
    starts.sort()
    # The last term that has already begun. Before the first, it is the first.
    term = sum(1 for start in starts if start <= on) or 1
    return TERM_LABEL.format(term=term, session=academic_session(on))


@router.post("/additions/quote", response_model=AdditionQuote)
async def quote_addition(
    payload: AdditionQuoteRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> AdditionQuote:
    """What adding people mid-term costs, before anybody confirms it.

    A school asks this before it asks for the people, and the answer for a
    teacher is nothing at all.

    Advisory, and deliberately so. Nothing here charges anything and no other
    route does either: enrolling a student has no billing side effect at all.
    What happens is that the next scheduled invoice counts active students and
    prices the term off that head count, so an addition reaches a school as a
    bigger next invoice rather than as a charge of its own. ``billed`` says so
    in the response, because a screen with a "charge now" button on this would
    be promising something the backend never does.

    The figure is also not prorated. It is the full per-student rate, so it is
    what that student costs for a whole term, not the remainder of this one.
    """

    actor = await require_school_actor(session, principal, roles=ADMIN_ROLES)
    school = await session.get(School, actor.school_id)
    assert school is not None
    quote = _quote(school, payload.students)
    teacher_note = (
        f"{payload.teachers} teacher accounts are free."
        if payload.teachers
        else "Teachers are free."
    )
    term = _current_term_label(school)
    return AdditionQuote(
        students=payload.students,
        teachers=payload.teachers,
        per_student_rate=quote.per_student_rate,
        amount=quote.total_with_vat,
        total_before_vat=quote.total_before_vat,
        vat_rate=quote.vat_rate,
        vat_amount=quote.vat_amount,
        total_with_vat=quote.total_with_vat,
        currency=quote.currency.value,
        applies_to=term,
        message=(
            f"{payload.students} students at {quote.per_student_rate} each, "
            f"{quote.total_with_vat} including VAT, on your next invoice. "
            f"{teacher_note}"
        ),
    )
