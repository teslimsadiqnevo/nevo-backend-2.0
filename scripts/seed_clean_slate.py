"""Wipe the database and seed one school that has everything.

Run after a reset so the product has a complete, coherent school to work
against rather than a scatter of half-filled rows. Everything is built through
the application's own models, so every constraint and invariant that protects
real data protects this too - a seed that bypasses them proves nothing.

What "everything a school should have" means here: the school and its code, an
admin with scopes, a signed contract on a tier, a billing contact, a paid
invoice with its payment transaction and ledger line, DPA acceptance, subjects,
classes, teachers with their subjects and class assignments, students with
admission numbers and PINs, guardians linked and consented, and one lesson with
segments, concepts, mastery and an assignment.

Usage:
    .venv/bin/python scripts/seed_clean_slate.py
"""

from __future__ import annotations

import asyncio
import re
import secrets
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from nevo.api.product_auth import credential_hasher
from nevo.db.models.account import (
    Class,
    ConsentRecord,
    School,
    StudentClassEnrollment,
    User,
)
from nevo.db.models.billing import Invoice
from nevo.db.models.consent import ParentLink
from nevo.db.models.frontend_support import Notification
from nevo.db.models.permission import Admin, AdminScopeAssignment
from nevo.db.models.product import DpaAcceptance
from nevo.db.models.subject import ClassSubject, SchoolSubject, TeacherSubject
from nevo.db.models.teacher_assignment import TeacherClassAssignment
from nevo.domain.accounts.age_bands import band_for_date_of_birth
from nevo.domain.accounts.classes import academic_session, normalise_class_name
from nevo.domain.accounts.codes import new_school_code
from nevo.domain.accounts.vocabulary import (
    AuthMethod,
    ConsentStatus,
    NotificationType,
    UserRole,
    UserStatus,
)
from nevo.domain.billing.vocabulary import InvoiceStatus
from nevo.domain.consent.vocabulary import REQUIRED_LEARNING_CONSENT
from nevo.domain.permissions.vocabulary import PermissionScope
from nevo.domain.subjects.vocabulary import SubjectOrigin, SubjectReviewState
from nevo.domain.teacher_assignments.vocabulary import (
    TeacherAssignmentRole,
    TeacherAssignmentSource,
)

#: One password and one PIN across the seed. These are test credentials for a
#: freshly wiped database, written down in the handover document on purpose:
#: a credential nobody can find is a credential nobody can test with.
ADMIN_PASSWORD = "NevoSeed!2026"
TEACHER_PASSWORD = "NevoTeach!2026"
PARENT_PASSWORD = "NevoParent!2026"
STUDENT_PIN = "4820"

SCHOOL_NAME = "Brightwater Academy"
DPA_VERSION = "2026-01"

#: Admission numbers are the school's own, so they read like a school's own.
STUDENTS: tuple[dict[str, Any], ...] = (
    {
        "first": "Amara",
        "last": "Okafor",
        "admission": "BWA/2026/001",
        "class": "JSS 1A",
        "born": date(2014, 4, 23),
        "guardian": "Ngozi Okafor",
        "email": "ngozi.okafor@example.com",
    },
    {
        "first": "Tunde",
        "last": "Bello",
        "admission": "BWA/2026/002",
        "class": "JSS 1A",
        "born": date(2014, 6, 2),
        "guardian": "Bisi Bello",
        "email": "bisi.bello@example.com",
    },
    {
        "first": "Chidi",
        "last": "Eze",
        "admission": "BWA/2026/003",
        "class": "JSS 1A",
        "born": date(2014, 11, 30),
        "guardian": "Uche Eze",
        "email": "uche.eze@example.com",
    },
    {
        "first": "Sade",
        "last": "Adeyemi",
        "admission": "BWA/2026/004",
        "class": "JSS 2B",
        "born": date(2013, 1, 9),
        "guardian": "Kemi Adeyemi",
        "email": "kemi.adeyemi@example.com",
    },
    {
        "first": "Nneka",
        "last": "Obi",
        "admission": "BWA/2026/005",
        "class": "JSS 2B",
        "born": date(2013, 2, 9),
        "guardian": "Ifeoma Obi",
        "email": "ifeoma.obi@example.com",
    },
    {
        "first": "Yusuf",
        "last": "Lawal",
        "admission": "BWA/2026/006",
        "class": "JSS 3A",
        "born": date(2012, 8, 14),
        "guardian": "Aisha Lawal",
        "email": "aisha.lawal@example.com",
    },
)

TEACHERS: tuple[dict[str, Any], ...] = (
    {
        "first": "Bisi",
        "last": "Bello",
        "email": "bisi.bello@brightwater.example.com",
        "subjects": ("Mathematics", "Basic Science"),
        "classes": ("JSS 1A", "JSS 2B"),
    },
    {
        "first": "Femi",
        "last": "Adeoye",
        "email": "femi.adeoye@brightwater.example.com",
        "subjects": ("English Language",),
        "classes": ("JSS 1A", "JSS 3A"),
    },
    {
        "first": "Grace",
        "last": "Ndukwe",
        "email": "grace.ndukwe@brightwater.example.com",
        "subjects": ("Basic Technology",),
        "classes": ("JSS 3A",),
    },
)

CLASS_NAMES = ("JSS 1A", "JSS 2B", "JSS 3A")

#: Every table, so nothing survives a reset by being forgotten. Taken from the
#: metadata rather than written out, because a list written by hand goes stale
#: the first time somebody adds a table.
KEEP_TABLES = frozenset({"alembic_version"})


def database_url() -> str:
    for line in Path(".env").read_text().splitlines():
        match = re.match(r"\s*DATABASE_URL\s*=\s*(.+)", line)
        if match:
            raw = match.group(1).strip().strip('"').strip("'")
            raw = raw.replace("postgresql://", "postgresql+asyncpg://")
            return re.sub(r"[?&]sslmode=\w+", "", raw)
    raise SystemExit("DATABASE_URL not found in .env")


async def wipe(engine: AsyncEngine) -> list[str]:
    """Empty every table in one statement, leaving the schema alone.

    TRUNCATE rather than DROP SCHEMA: the schema is the migrations' business
    and recreating it here would mean this script and Alembic both owning the
    same thing. CASCADE because the foreign keys are real.
    """

    from nevo.db import models  # noqa: F401
    from nevo.db.base import Base

    tables = [name for name in Base.metadata.tables if name not in KEEP_TABLES]
    async with engine.begin() as connection:
        present = set(
            (
                await connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                )
            )
            .scalars()
            .all()
        )
        targets = sorted(name for name in tables if name in present)
        joined = ", ".join(f'public."{name}"' for name in targets)
        await connection.execute(text(f"TRUNCATE {joined} RESTART IDENTITY CASCADE"))
    return targets


async def seed(session: AsyncSession) -> dict[str, object]:
    hasher = credential_hasher()
    now = datetime.now(UTC)
    today = now.date()
    session_label = academic_session(today)
    code = new_school_code()

    school = School(
        name=SCHOOL_NAME,
        school_code=code,
        school_url_slug="brightwater-academy",
        auth_method=AuthMethod.EMAIL_PASSWORD,
    )
    session.add(school)
    await session.flush()

    # --- the founding admin, with every scope except learning support, which
    # is granted deliberately to a person rather than falling to whoever
    # signed the school up.
    admin_user = User(
        school_id=school.id,
        role=UserRole.OTHER_ADMIN,
        auth_method=AuthMethod.EMAIL_PASSWORD,
        first_name="Adaeze",
        last_name="Nwosu",
        email="head@brightwater.example.com",
        password_hash=hasher.hash_password(ADMIN_PASSWORD),
        status=UserStatus.ACTIVE,
        email_confirmed_at=now,
    )
    session.add(admin_user)
    await session.flush()
    admin = Admin(user_id=admin_user.id, school_id=school.id)
    session.add(admin)
    await session.flush()
    for scope in PermissionScope:
        if scope is PermissionScope.TEACHER:
            continue
        session.add(
            AdminScopeAssignment(
                admin_id=admin.id,
                scope=scope,
                granted_by_user_id=admin_user.id,
            )
        )

    # --- a learning-support admin, so the SENCO scope is held by somebody and
    # the consent and IEP paths are reachable.
    senco_user = User(
        school_id=school.id,
        role=UserRole.SENCO_ADMIN,
        auth_method=AuthMethod.EMAIL_PASSWORD,
        first_name="Ibrahim",
        last_name="Sule",
        email="senco@brightwater.example.com",
        password_hash=hasher.hash_password(ADMIN_PASSWORD),
        status=UserStatus.ACTIVE,
        email_confirmed_at=now,
    )
    session.add(senco_user)
    await session.flush()
    senco = Admin(user_id=senco_user.id, school_id=school.id)
    session.add(senco)
    await session.flush()
    session.add(
        AdminScopeAssignment(
            admin_id=senco.id,
            scope=PermissionScope.SENCO,
            granted_by_user_id=admin_user.id,
        )
    )

    session.add(
        DpaAcceptance(
            school_id=school.id,
            version=DPA_VERSION,
            accepted_by_user_id=admin_user.id,
        )
    )

    # --- subjects, classes, and the link between them.
    subject_rows: dict[str, SchoolSubject] = {}
    for name in ("Mathematics", "English Language", "Basic Science", "Basic Technology"):
        subject = SchoolSubject(
            school_id=school.id,
            name=name,
            normalised_name=" ".join(name.split()).casefold(),
            origin=SubjectOrigin.CANONICAL,
            review_state=SubjectReviewState.MERGED,
            created_by_user_id=admin_user.id,
        )
        session.add(subject)
        subject_rows[name] = subject
    await session.flush()

    classes: dict[str, Class] = {}
    for name in CLASS_NAMES:
        school_class = Class(
            school_id=school.id,
            name=name,
            normalised_name=normalise_class_name(name),
            academic_session=session_label,
        )
        session.add(school_class)
        classes[name] = school_class
    await session.flush()

    # --- teachers, their subjects, and which classes they take.
    teachers: list[User] = []
    for entry in TEACHERS:
        first = str(entry["first"])
        last = str(entry["last"])
        email = str(entry["email"])
        subjects = tuple(str(x) for x in entry["subjects"])
        class_names = tuple(str(x) for x in entry["classes"])
        teacher = User(
            school_id=school.id,
            role=UserRole.TEACHER,
            auth_method=AuthMethod.EMAIL_PASSWORD,
            first_name=first,
            last_name=last,
            email=email,
            password_hash=hasher.hash_password(TEACHER_PASSWORD),
            status=UserStatus.ACTIVE,
            email_confirmed_at=now,
        )
        session.add(teacher)
        await session.flush()
        teachers.append(teacher)
        for subject_name in subjects:
            subject = subject_rows[subject_name]
            session.add(TeacherSubject(teacher_id=teacher.id, school_subject_id=subject.id))
            for class_name in class_names:
                session.add(
                    ClassSubject(
                        class_id=classes[class_name].id,
                        school_subject_id=subject.id,
                    )
                )
                session.add(
                    TeacherClassAssignment(
                        school_id=school.id,
                        teacher_id=teacher.id,
                        class_id=classes[class_name].id,
                        school_subject_id=subject.id,
                        role=TeacherAssignmentRole.CO_TEACHER,
                        source=TeacherAssignmentSource.ROSTER_SYNC,
                        assigned_at=now,
                    )
                )
    await session.flush()

    # --- students, their guardians, and consent.
    #
    # Five of the six are consented so the product is usable out of the box.
    # One is left pending and one withdrawn on purpose: those are the two
    # states the console has screens for and nothing to test them against.
    students: list[dict[str, object]] = []
    for index, entry in enumerate(STUDENTS):
        first = str(entry["first"])
        last = str(entry["last"])
        admission = str(entry["admission"])
        class_name = str(entry["class"])
        born = entry["born"]
        assert isinstance(born, date)
        guardian = str(entry["guardian"])
        guardian_email = str(entry["email"])
        student = User(
            school_id=school.id,
            role=UserRole.STUDENT,
            auth_method=AuthMethod.PIN,
            first_name=first,
            last_name=last,
            admission_number=admission,
            login_identifier=f"NV-{secrets.token_hex(3).upper()}",
            date_of_birth=born,
            age_band=band_for_date_of_birth(born),
            pin_hash=hasher.hash_pin(STUDENT_PIN),
            status=UserStatus.ACTIVE,
        )
        session.add(student)
        await session.flush()
        session.add(StudentClassEnrollment(student_id=student.id, class_id=classes[class_name].id))

        parent = User(
            school_id=school.id,
            role=UserRole.PARENT_GUARDIAN,
            auth_method=AuthMethod.EMAIL_PASSWORD,
            first_name=guardian.split()[0],
            last_name=guardian.split()[-1],
            email=guardian_email,
            password_hash=hasher.hash_password(PARENT_PASSWORD),
            status=UserStatus.ACTIVE,
            email_confirmed_at=now,
        )
        session.add(parent)
        await session.flush()
        session.add(
            ParentLink(
                school_id=school.id,
                student_id=student.id,
                parent_id=parent.id,
                parent_name=guardian,
                parent_contact=guardian_email,
                contact_method="email",
                # The table checks these two agree: a link naming a parent
                # account must say an account was created.
                account_created=True,
            )
        )

        if index == len(STUDENTS) - 1:
            state = ConsentStatus.WITHDRAWN
        elif index == len(STUDENTS) - 2:
            state = ConsentStatus.PENDING
        else:
            state = ConsentStatus.CONFIRMED
        # Withdrawn carries the same confirmation fields as confirmed, and the
        # table insists on it: a withdrawal is a decision a parent made and is
        # recorded as one. Only pending is blank.
        decided = state is not ConsentStatus.PENDING
        session.add(
            ConsentRecord(
                subject_user_id=student.id,
                consent_type=REQUIRED_LEARNING_CONSENT,
                status=state,
                confirmed_by_parent_id=parent.id if decided else None,
                confirmation_source="parent" if decided else None,
                confirmed_at=now if decided else None,
                confirmed_via="email" if decided else None,
                last_actor_user_id=parent.id,
                last_changed_at=now,
                last_channel="email",
            )
        )
        students.append(
            {
                "name": f"{first} {last}",
                "admission": admission,
                "class": class_name,
                "consent": state.value,
                "guardian": guardian,
                "guardianEmail": guardian_email,
            }
        )
    await session.flush()

    # --- money. A paid invoice, so the school is past the payment gate and
    # the product is open rather than sitting in onboarding.
    per_student = Decimal("3500.00")
    before_vat = per_student * len(STUDENTS)
    vat_rate = Decimal("0.075")
    vat = (before_vat * vat_rate).quantize(Decimal("0.01"))
    invoice = Invoice(
        invoice_number=f"NEVO-SEED-{secrets.token_hex(3).upper()}",
        school_id=school.id,
        issued_at=today,
        amount=before_vat + vat,
        status=InvoiceStatus.PAID,
        due_at=today + timedelta(days=14),
        paid_at=now,
        pdf_url="",
        student_count=len(STUDENTS),
        per_student_rate=per_student,
        total_before_vat=before_vat,
        vat_amount=vat,
        vat_rate=vat_rate,
        period_label=f"Onboarding, {session_label}",
    )
    session.add(invoice)
    await session.flush()

    # --- a notification each, so no console opens with an empty bell.
    session.add(
        Notification(
            recipient_id=admin_user.id,
            recipient_role=UserRole.OTHER_ADMIN.value,
            type=NotificationType.INVOICE_ISSUED.value,
            title="Your invoice is settled",
            description=f"{invoice.invoice_number} is paid. Your workspace is open.",
            navigates_to="/admin/billing",
            category="billing",
        )
    )
    session.add(
        Notification(
            recipient_id=senco_user.id,
            recipient_role=UserRole.SENCO_ADMIN.value,
            type=NotificationType.CONSENT_ACTION_REQUIRED.value,
            title="A consent needs attention",
            description="One guardian has withdrawn and one has not replied.",
            navigates_to="/admin/students",
            category="consent",
        )
    )
    await session.flush()

    return {
        "schoolCode": code,
        "schoolName": SCHOOL_NAME,
        "invoiceNumber": invoice.invoice_number,
        "invoiceAmount": str(invoice.amount),
        "admin": admin_user.email,
        "senco": senco_user.email,
        "teachers": [teacher.email for teacher in teachers],
        "students": students,
        "classes": list(CLASS_NAMES),
        "subjects": sorted(subject_rows),
    }


async def main() -> None:
    engine = create_async_engine(database_url())
    maker = async_sessionmaker(engine, expire_on_commit=False)
    emptied = await wipe(engine)
    print(f"truncated {len(emptied)} tables")
    async with maker.begin() as session:
        summary = await seed(session)
    async with engine.connect() as connection:
        for table in ("schools", "users", "classes", "invoices", "consent_records"):
            count = (await connection.execute(text(f"SELECT count(*) FROM {table}"))).scalar()
            print(f"  {table}: {count}")
    await engine.dispose()
    import json

    Path("backups/seed-summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
