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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.api.auth import PrincipalDependency
from nevo.api.casing import CAMEL_CONFIG
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_common import require_school_actor
from nevo.api.response_models import CamelResponse
from nevo.billing.entities import PerStudentQuote
from nevo.billing.service import quote_per_student
from nevo.db.models.account import Class, School, StudentClassEnrollment, User
from nevo.db.models.billing import Invoice
from nevo.db.models.onboarding import OnboardingRow, SchoolOnboarding
from nevo.domain.accounts.classes import academic_session, normalise_class_name, parse_class_name
from nevo.domain.accounts.vocabulary import AuthMethod, UserRole, UserStatus
from nevo.domain.billing.vocabulary import InvoiceStatus, RateType
from nevo.domain.onboarding.vocabulary import OnboardingRowKind, OnboardingStage

router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])

ADMIN_ROLES = {"senco_admin", "other_admin"}

#: A school file is a spreadsheet exported as CSV. Anything larger than this
#: is not a school's roster, and reading it into memory would be a way to take
#: the API down from a file upload.
MAX_UPLOAD_BYTES = 2_000_000

#: What each template asks for. Parent details are mandatory on a student row,
#: because a child whose parent cannot be reached cannot be consented for.
STUDENT_COLUMNS = (
    "first_name",
    "last_name",
    "class",
    "date_of_birth",
    "parent_name",
    "parent_email",
)
TEACHER_COLUMNS = ("first_name", "last_name", "email", "class")

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
    students: int
    teachers: int
    per_student_rate: Decimal
    amount: Decimal
    currency: str
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

    wanted = STUDENT_COLUMNS if kind is OnboardingRowKind.STUDENT else TEACHER_COLUMNS
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
    missing = [column for column in wanted if column not in headers]
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
        _reject_incomplete(row, values, wanted)
        rows.append(row)
    return rows


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


def _column(name: str) -> str:
    return name.strip().casefold().replace(" ", "_")


@router.get("", response_model=OnboardingState)
async def read_onboarding(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> OnboardingState:
    actor = await require_school_actor(session, principal, roles=ADMIN_ROLES)
    record = await _onboarding(session, actor.school_id)
    state = await _state_for(session, record)
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
    record.activated_at = datetime.now(UTC)
    record.stage = OnboardingStage.ACTIVATED
    await session.flush()
    state = await _state_for(session, record)
    await session.commit()
    return state


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
    user = User(
        school_id=school.id,
        role=UserRole.STUDENT if is_student else UserRole.TEACHER,
        date_of_birth=_parse_date(values.get("date_of_birth", "")) if is_student else None,
        auth_method=AuthMethod.EMAIL_PASSWORD,
        first_name=first_name,
        last_name=last_name,
        email=(values.get("email") or "").casefold() or None,
        status=UserStatus.ACTIVE if is_student else UserStatus.INVITED,
    )
    session.add(user)
    await session.flush()
    school_class = classes.get(row.normalised_class_name or "")
    if is_student and school_class is not None:
        session.add(StudentClassEnrollment(student_id=user.id, class_id=school_class.id))


@router.post("/additions/quote", response_model=AdditionQuote)
async def quote_addition(
    payload: AdditionQuoteRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> AdditionQuote:
    """What adding people mid-term costs, before anybody confirms it.

    A school asks this before it asks for the people, and the answer for a
    teacher is nothing at all.
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
    return AdditionQuote(
        students=payload.students,
        teachers=payload.teachers,
        per_student_rate=quote.per_student_rate,
        amount=quote.total_with_vat,
        currency=quote.currency.value,
        message=(
            f"{payload.students} students at {quote.per_student_rate} each, "
            f"{quote.total_with_vat} including VAT. {teacher_note}"
        ),
    )
