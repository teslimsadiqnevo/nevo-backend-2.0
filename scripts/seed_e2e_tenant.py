"""The E2E tenant, built to the shapes the admin console needs to be tested.

Not a tidy school. A tidy school renders every screen and proves almost
nothing: every counting bug this console has shipped lived in the gap between
a number and the right number - a count capped at a page boundary, a count of
flags rendered under the word "students", an absent value rendered as a zero,
a partial read rendered as a total. None of those shows itself unless the data
crosses the threshold that triggers it.

So the numbers here are chosen to cross those thresholds, from Olayinka's
specification of 14 September:

* consent states mixed, so "without recorded consent" and "withdrawn" come out
  as different numbers rather than coinciding
* one student with no consent record at all, because unknown must not render
  as nobody asked
* flags concentrated on fewer children than there are flags, so a count of
  flags and a count of children differ
* more than 200 flags, past the cap on GET /api/intelligence/flags
* more than 100 adaptation events in a week, past the cap on the adaptation
  log, so its paging loop runs for the first time against a real backend
* classes that are not all tidy: one archived, one with no teacher, one with a
  primary and a co-teacher
* observations with a count, with a null count, and absent entirely

Synthetic names throughout. Nothing here depends on the data being plausible
as people, and real-looking children in a test tenant is a liability.

Usage:
    .venv/bin/python scripts/seed_e2e_tenant.py
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import re
import secrets
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nevo.api.product_auth import credential_hasher
from nevo.db.models.account import (
    Class,
    ConsentRecord,
    School,
    StudentClassEnrollment,
    User,
)
from nevo.db.models.attention_flag import AttentionFlag
from nevo.db.models.billing import (
    BillingContact,
    BillingPaymentMethod,
    BillingSubscriptionTier,
    Contract,
    Invoice,
)
from nevo.db.models.consent import ParentLink
from nevo.db.models.content import ContentParseRun, Lesson, LessonSegment
from nevo.db.models.frontend_support import Concept, LessonAssignment
from nevo.db.models.permission import Admin, AdminScopeAssignment
from nevo.db.models.product import DpaAcceptance, SchoolInvitation
from nevo.db.models.signal_event import LessonSession, SignalEvent
from nevo.db.models.sso import RosterSyncIssue, RosterSyncRun, SchoolSsoConfiguration
from nevo.db.models.teacher_assignment import TeacherClassAssignment
from nevo.domain.accounts.age_bands import band_for_date_of_birth
from nevo.domain.accounts.classes import academic_session, normalise_class_name
from nevo.domain.accounts.codes import new_school_code
from nevo.domain.accounts.vocabulary import (
    AuthMethod,
    ConsentStatus,
    UserRole,
    UserStatus,
)
from nevo.domain.attention_flags.vocabulary import AttentionFlagType
from nevo.domain.billing.vocabulary import (
    ContractStatus,
    InvoiceStatus,
    PaymentSource,
)
from nevo.domain.consent.vocabulary import REQUIRED_LEARNING_CONSENT
from nevo.domain.permissions.vocabulary import PermissionScope
from nevo.domain.signal_events.vocabulary import SignalEventType
from nevo.domain.teacher_assignments.vocabulary import (
    TeacherAssignmentRole,
    TeacherAssignmentSource,
)

SCHOOL_NAME = "E2E Test Academy (not a customer)"
ADMIN_PASSWORD = "NevoE2E!2026"
TEACHER_PASSWORD = "NevoE2E!2026"
STUDENT_PIN = "4820"

#: Seeded so two runs produce the same tenant. A test that passes against one
#: shuffle and fails against the next is a test nobody trusts.
RANDOM = random.Random(20260914)

#: Consent spread. The whole point: "without recorded consent" is everything
#: but confirmed, "withdrawn" is withdrawn only, and on a uniform tenant the
#: two coincide and a conflation bug is invisible.
CONSENT_PLAN: tuple[tuple[ConsentStatus | None, int], ...] = (
    (ConsentStatus.CONFIRMED, 20),
    (ConsentStatus.PENDING, 8),
    # not_sent is a different claim from pending and must not appear in the
    # Overview's "waiting on parent consent" row.
    (ConsentStatus.NOT_SENT, 8),
    (ConsentStatus.WITHDRAWN, 3),
    # None means no consent record at all. The NDPA coverage row refuses to
    # show a figure if any student comes back without one, and that refusal
    # has never been exercised.
    (None, 1),
)

CLASSES: tuple[dict[str, object], ...] = (
    {"name": "JSS 1A", "shape": "primary_and_co"},
    {"name": "JSS 1B", "shape": "primary_only"},
    {"name": "JSS 2A", "shape": "primary_only"},
    {"name": "JSS 2B", "shape": "no_teacher"},
    {"name": "JSS 3A", "shape": "primary_only"},
    {"name": "JSS 3B", "shape": "primary_only"},
    {"name": "SS 1 Science", "shape": "primary_only"},
    {"name": "SS 2 Arts (archived)", "shape": "archived"},
)

SUBJECTS = ("Mathematics", "English Language", "Basic Science", "Basic Technology")

#: The two the enum actually holds. Invented names were refused by the
#: database, which is the check doing its job.
FLAG_TYPES = tuple(AttentionFlagType)

#: Past the cap on GET /api/intelligence/flags, so the paging loop runs.
TOTAL_FLAGS = 240
#: Fewer children than flags, so a count of children and a count of flags
#: cannot come out the same.
FLAGGED_STUDENTS = 8

#: Past the cap of 100 on the adaptation log, so three pages are needed.
ADAPTATION_EVENTS = 250
ADAPTATION_STUDENTS = 15

ADAPTATION_TYPES = (
    SignalEventType.SIMPLIFY_TRIGGER,
    SignalEventType.EXPAND_TRIGGER,
    SignalEventType.SLOWER_TRIGGER,
    SignalEventType.BREAK_SUGGESTED,
    SignalEventType.MODALITY_SUGGESTION_SHOWN,
    SignalEventType.MODALITY_SUGGESTION_ACCEPTED,
    SignalEventType.MODALITY_SWITCH_OUTCOME,
    SignalEventType.MODALITY_MANUAL_SWITCH,
)

FIRST_NAMES = (
    "Ada",
    "Bem",
    "Chi",
    "Dayo",
    "Efe",
    "Fola",
    "Gozi",
    "Hauwa",
    "Ife",
    "Jide",
    "Kene",
    "Lami",
    "Mide",
    "Nura",
    "Obi",
    "Peju",
    "Qudus",
    "Rume",
    "Simi",
    "Tari",
    "Uche",
    "Vera",
    "Wale",
    "Yemi",
    "Zara",
    "Amad",
    "Binta",
    "Chuka",
    "Dele",
    "Eniola",
    "Funke",
    "Gbemi",
    "Hadiza",
    "Ismail",
    "Jumoke",
    "Kola",
    "Lara",
    "Musa",
    "Ngozi",
    "Olu",
)
LAST_NAMES = (
    "Test",
    "Sample",
    "Fixture",
    "Dummy",
    "Placeholder",
    "Mock",
    "Stub",
    "Example",
)


def database_url() -> str:
    for line in Path(".env").read_text().splitlines():
        match = re.match(r"\s*DATABASE_URL\s*=\s*(.+)", line)
        if match:
            raw = match.group(1).strip().strip('"').strip("'")
            raw = raw.replace("postgresql://", "postgresql+asyncpg://")
            return re.sub(r"[?&]sslmode=\w+", "", raw)
    raise SystemExit("DATABASE_URL not found in .env")


async def seed(session: AsyncSession) -> dict[str, object]:
    hasher = credential_hasher()
    now = datetime.now(UTC)
    today = now.date()
    session_label = academic_session(today)
    code = new_school_code()

    school = School(
        name=SCHOOL_NAME,
        school_code=code,
        school_url_slug=f"e2e-test-academy-{secrets.token_hex(2)}",
        auth_method=AuthMethod.EMAIL_PASSWORD,
    )
    session.add(school)
    await session.flush()

    admin_user = User(
        school_id=school.id,
        role=UserRole.OTHER_ADMIN,
        auth_method=AuthMethod.EMAIL_PASSWORD,
        first_name="E2E",
        last_name="Admin",
        email="e2e.admin@e2e.example.com",
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
            AdminScopeAssignment(admin_id=admin.id, scope=scope, granted_by_user_id=admin_user.id)
        )

    senco_user = User(
        school_id=school.id,
        role=UserRole.SENCO_ADMIN,
        auth_method=AuthMethod.EMAIL_PASSWORD,
        first_name="E2E",
        last_name="Senco",
        email="e2e.senco@e2e.example.com",
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
        DpaAcceptance(school_id=school.id, version="2026-01", accepted_by_user_id=admin_user.id)
    )

    # --- subjects
    from nevo.db.models.subject import ClassSubject, SchoolSubject, TeacherSubject
    from nevo.domain.subjects.vocabulary import SubjectOrigin, SubjectReviewState

    subjects: dict[str, SchoolSubject] = {}
    for name in SUBJECTS:
        subject = SchoolSubject(
            school_id=school.id,
            name=name,
            normalised_name=" ".join(name.split()).casefold(),
            origin=SubjectOrigin.CANONICAL,
            review_state=SubjectReviewState.MERGED,
            created_by_user_id=admin_user.id,
        )
        session.add(subject)
        subjects[name] = subject
    await session.flush()

    # --- classes, one archived
    classes: dict[str, Class] = {}
    for entry in CLASSES:
        name = str(entry["name"])
        school_class = Class(
            school_id=school.id,
            name=name,
            normalised_name=normalise_class_name(name),
            academic_session=session_label,
            # Archiving is reversible and must not read as deleted.
            archived_at=now - timedelta(days=40) if entry["shape"] == "archived" else None,
        )
        session.add(school_class)
        classes[name] = school_class
    await session.flush()

    # --- teachers in the three shapes the spec asks for
    teachers: dict[str, User] = {}

    def add_teacher(first: str, last: str, email: str, status: UserStatus) -> User:
        teacher = User(
            school_id=school.id,
            role=UserRole.TEACHER,
            auth_method=AuthMethod.EMAIL_PASSWORD,
            first_name=first,
            last_name=last,
            email=email,
            password_hash=(
                hasher.hash_password(TEACHER_PASSWORD) if status is UserStatus.ACTIVE else None
            ),
            status=status,
            email_confirmed_at=now if status is UserStatus.ACTIVE else None,
        )
        session.add(teacher)
        teachers[email] = teacher
        return teacher

    # Four or more classes, which is what forces the reassignment flow when
    # somebody tries to remove them.
    busy = add_teacher("Busy", "Teacher", "busy.teacher@e2e.example.com", UserStatus.ACTIVE)
    spare = add_teacher("Spare", "Teacher", "spare.teacher@e2e.example.com", UserStatus.ACTIVE)
    co = add_teacher("Co", "Teacher", "co.teacher@e2e.example.com", UserStatus.ACTIVE)
    # Invited and never joined: no password, status invited.
    add_teacher("Invited", "Teacher", "invited.teacher@e2e.example.com", UserStatus.INVITED)
    await session.flush()

    session.add(
        SchoolInvitation(
            school_id=school.id,
            role="teacher",
            first_name="Invited",
            last_name="Teacher",
            email="invited.teacher@e2e.example.com",
            token_digest=hashlib.sha256(secrets.token_urlsafe(32).encode()).hexdigest(),
            expires_at=now + timedelta(days=14),
            created_by_id=admin_user.id,
        )
    )

    busy_classes = ["JSS 1A", "JSS 1B", "JSS 2A", "JSS 3A", "JSS 3B"]
    assignments = 0
    for offset, name in enumerate(busy_classes):
        session.add(
            TeacherClassAssignment(
                school_id=school.id,
                teacher_id=busy.id,
                class_id=classes[name].id,
                school_subject_id=subjects["Mathematics"].id,
                role=TeacherAssignmentRole.PRIMARY,
                source=TeacherAssignmentSource.MANUAL,
                # Months apart, because the dates render on both class and
                # teacher detail and all-identical dates prove nothing.
                assigned_at=now - timedelta(days=30 * (offset + 1)),
            )
        )
        assignments += 1
    # JSS 1A also gets a co-teacher, so one class has both shapes.
    session.add(
        TeacherClassAssignment(
            school_id=school.id,
            teacher_id=co.id,
            class_id=classes["JSS 1A"].id,
            school_subject_id=subjects["Basic Science"].id,
            role=TeacherAssignmentRole.CO_TEACHER,
            source=TeacherAssignmentSource.MANUAL,
            assigned_at=now - timedelta(days=12),
        )
    )
    assignments += 1
    session.add(
        TeacherClassAssignment(
            school_id=school.id,
            teacher_id=spare.id,
            class_id=classes["SS 1 Science"].id,
            school_subject_id=subjects["English Language"].id,
            role=TeacherAssignmentRole.PRIMARY,
            source=TeacherAssignmentSource.MANUAL,
            assigned_at=now - timedelta(days=200),
        )
    )
    assignments += 1
    # JSS 2B deliberately has nobody, for the "No teacher yet" state.

    for teacher in (busy, spare, co):
        for name in ("Mathematics", "Basic Science", "English Language"):
            session.add(TeacherSubject(teacher_id=teacher.id, school_subject_id=subjects[name].id))
    for school_class in classes.values():
        for name in ("Mathematics", "English Language"):
            session.add(ClassSubject(class_id=school_class.id, school_subject_id=subjects[name].id))
    await session.flush()

    # --- students, spread across the consent states
    teachable = [
        name
        for name, entry in zip([str(c["name"]) for c in CLASSES], CLASSES, strict=True)
        if entry["shape"] != "archived"
    ]
    students: list[User] = []
    consent_counts: dict[str, int] = {}
    index = 0
    for state, how_many in CONSENT_PLAN:
        for _ in range(how_many):
            first = FIRST_NAMES[index % len(FIRST_NAMES)]
            last = LAST_NAMES[index % len(LAST_NAMES)]
            born = date(2013, 1, 1) + timedelta(days=RANDOM.randint(0, 900))
            student = User(
                school_id=school.id,
                role=UserRole.STUDENT,
                auth_method=AuthMethod.PIN,
                first_name=first,
                last_name=last,
                admission_number=f"E2E/{index + 1:03d}",
                login_identifier=f"NV-{secrets.token_hex(3).upper()}",
                date_of_birth=born,
                age_band=band_for_date_of_birth(born),
                pin_hash=hasher.hash_pin(STUDENT_PIN),
                status=UserStatus.ACTIVE,
            )
            session.add(student)
            await session.flush()
            students.append(student)
            session.add(
                StudentClassEnrollment(
                    student_id=student.id,
                    class_id=classes[teachable[index % len(teachable)]].id,
                )
            )

            if state is not None:
                parent = User(
                    school_id=school.id,
                    role=UserRole.PARENT_GUARDIAN,
                    auth_method=AuthMethod.EMAIL_PASSWORD,
                    first_name="Guardian",
                    last_name=f"Of{index + 1:03d}",
                    email=f"guardian{index + 1:03d}@e2e.example.com",
                    password_hash=hasher.hash_password(ADMIN_PASSWORD),
                    status=UserStatus.ACTIVE,
                )
                session.add(parent)
                await session.flush()
                session.add(
                    ParentLink(
                        school_id=school.id,
                        student_id=student.id,
                        parent_id=parent.id,
                        parent_name=f"Guardian Of{index + 1:03d}",
                        parent_contact=f"guardian{index + 1:03d}@e2e.example.com",
                        contact_method="email",
                        account_created=True,
                    )
                )
                decided = state in {ConsentStatus.CONFIRMED, ConsentStatus.WITHDRAWN}
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
            consent_counts[state.value if state else "no_record"] = (
                consent_counts.get(state.value if state else "no_record", 0) + 1
            )
            index += 1
    await session.flush()

    # --- a lesson, so sessions and adaptation events have something to hang on
    concept = Concept(school_id=school.id, name="Fractions", subject="Mathematics", source="seed")
    session.add(concept)
    lesson = Lesson(
        created_by_user_id=busy.id,
        school_id=school.id,
        title="E2E fixture lesson",
        source_type="text",
        description="A fixture lesson for the E2E tenant.",
    )
    session.add(lesson)
    await session.flush()
    parse_run = ContentParseRun(
        lesson_id=lesson.id, requested_by_user_id=busy.id, source_type="text"
    )
    session.add(parse_run)
    await session.flush()
    session.add(
        LessonSegment(
            lesson_id=lesson.id,
            parse_run_id=parse_run.id,
            segment_key="intro",
            content_type="explanatory_text",
            sequence_order=1,
            title="Intro",
            body="A fixture segment.",
            available_modalities=["text"],
        )
    )
    for student in students[:10]:
        session.add(
            LessonAssignment(
                lesson_id=lesson.id,
                student_id=student.id,
                teacher_id=busy.id,
                assigned_at=now,
            )
        )
    await session.flush()

    # --- attention flags: more flags than children, mixed acknowledgement
    flagged = students[:FLAGGED_STUDENTS]
    acknowledged = 0
    for number in range(TOTAL_FLAGS):
        student = flagged[number % len(flagged)]
        is_acknowledged = number % 3 == 0
        if is_acknowledged:
            acknowledged += 1
        session.add(
            AttentionFlag(
                student_id=student.id,
                flag_type=FLAG_TYPES[number % len(FLAG_TYPES)],
                description="A fixture flag for the E2E tenant.",
                generated_at=now - timedelta(hours=number % 160),
                acknowledged_at=now - timedelta(hours=1) if is_acknowledged else None,
                acknowledged_by=senco_user.id if is_acknowledged else None,
            )
        )
    await session.flush()

    # --- adaptation events, past the log's page size, spread over the week
    adapting = students[:ADAPTATION_STUDENTS]
    sessions_by_student: dict[int, LessonSession] = {}
    for position, student in enumerate(adapting):
        lesson_session = LessonSession(
            # The client supplies this id; there is no server default on it.
            id=uuid4(),
            student_id=student.id,
            lesson_id=lesson.id,
            session_type="lesson",
            started_at=now - timedelta(days=position % 7, hours=1),
            ended_at=now - timedelta(days=position % 7),
            completion_status="completed",
        )
        session.add(lesson_session)
        sessions_by_student[position] = lesson_session
    await session.flush()

    for number in range(ADAPTATION_EVENTS):
        position = number % len(adapting)
        session.add(
            SignalEvent(
                student_id=adapting[position].id,
                session_id=sessions_by_student[position].id,
                event_type=ADAPTATION_TYPES[number % len(ADAPTATION_TYPES)],
                event_data={"segmentId": f"seg-{number % 5}", "fixture": True},
                # Spread across the week rather than stacked at one instant,
                # so date filtering and ordering have something to do.
                timestamp=now - timedelta(days=number % 7, minutes=number % 900),
            )
        )
    await session.flush()

    # --- SSO: connected, with a failed run carrying issues
    session.add(
        SchoolSsoConfiguration(
            school_id=school.id,
            provider="google",
            hosted_domain="e2e.example.com",
            client_id="e2e-fixture-client",
            school_url_slug=school.school_url_slug,
            enabled=True,
            connection_status="connected",
            connection_checked_at=now - timedelta(hours=2),
            next_scheduled_sync_at=now + timedelta(days=1),
        )
    )
    await session.flush()

    runs = (
        ("completed", None, 0, now - timedelta(days=9)),
        ("completed", None, 0, now - timedelta(days=6)),
        # The one that makes "View technical details" render at all.
        ("failed", "provider_rejected_credentials", 0, now - timedelta(days=3)),
        ("partial_manual_review", None, 4, now - timedelta(days=1)),
    )
    issue_count = 0
    for status_value, failure, missing, started in runs:
        run = RosterSyncRun(
            school_id=school.id,
            provider="google",
            status=status_value,
            imported_students=38 if status_value != "failed" else 0,
            imported_teachers=4 if status_value != "failed" else 0,
            missing_teacher_class_mappings=missing,
            failure_reason=failure,
            triggered_manually=False,
            triggered_by_user_id=admin_user.id,
            started_at=started,
            completed_at=started + timedelta(minutes=4),
        )
        session.add(run)
        await session.flush()
        if status_value in {"failed", "partial_manual_review"}:
            for number in range(3):
                session.add(
                    RosterSyncIssue(
                        roster_sync_run_id=run.id,
                        school_id=school.id,
                        external_reference=f"ext-{status_value}-{number}",
                        description="A fixture sync issue for the E2E tenant.",
                        resolution_hint="Map this teacher to a class in the console.",
                        status="open",
                    )
                )
                issue_count += 1
    await session.flush()

    # --- billing: one unpaid, one paid, a card on file, contract dates
    per_student = Decimal("3500.00")
    paid = Invoice(
        invoice_number=f"NEVO-E2E-{secrets.token_hex(3).upper()}",
        school_id=school.id,
        issued_at=today - timedelta(days=60),
        amount=Decimal("150500.00"),
        status=InvoiceStatus.PAID,
        due_at=today - timedelta(days=46),
        paid_at=now - timedelta(days=50),
        pdf_url="",
        student_count=40,
        per_student_rate=per_student,
        total_before_vat=Decimal("140000.00"),
        vat_amount=Decimal("10500.00"),
        vat_rate=Decimal("0.075"),
        period_label=f"Term 1 · {session_label}",
    )
    unpaid = Invoice(
        invoice_number=f"NEVO-E2E-{secrets.token_hex(3).upper()}",
        school_id=school.id,
        issued_at=today - timedelta(days=5),
        amount=Decimal("150500.00"),
        status=InvoiceStatus.PENDING,
        due_at=today + timedelta(days=9),
        pdf_url="",
        student_count=40,
        per_student_rate=per_student,
        total_before_vat=Decimal("140000.00"),
        vat_amount=Decimal("10500.00"),
        vat_rate=Decimal("0.075"),
        period_label=f"Term 2 · {session_label}",
    )
    session.add_all([paid, unpaid])
    session.add(
        BillingPaymentMethod(
            school_id=school.id,
            method_type="card",
            processor_name="paystack",
            processor_payment_method_ref="PM_E2E_FIXTURE",
            display_name="Visa ending 4081",
            last_four="4081",
            card_brand="visa",
            expiry_month=11,
            expiry_year=2029,
            is_reusable=True,
            updated_by_user_id=admin_user.id,
        )
    )
    session.add(
        BillingContact(
            school_id=school.id,
            email="finance@e2e.example.com",
            phone="+2348000000000",
            address_line1="1 Fixture Road",
            city="Lagos",
            country="NG",
            updated_by_user_id=admin_user.id,
        )
    )
    # The tier list is reference data the migrations seed; the contract points
    # at whichever band this headcount falls in rather than inventing one.
    tier_id = await session.scalar(
        select(BillingSubscriptionTier.tier_id)
        .where(
            BillingSubscriptionTier.min_pupils <= len(students),
            BillingSubscriptionTier.max_pupils >= len(students),
        )
        .limit(1)
    )
    if tier_id is None:
        tier_id = await session.scalar(select(BillingSubscriptionTier.tier_id).limit(1))
    if tier_id is not None:
        session.add(
            Contract(
                school_id=school.id,
                tier_id=tier_id,
                status=ContractStatus.ACTIVE,
                is_founding_partner=True,
                payment_source=PaymentSource.DIRECT,
                start_date=today - timedelta(days=60),
                end_date=today + timedelta(days=305),
                current_year_index=1,
            )
        )
    await session.flush()

    return {
        "schoolCode": code,
        "schoolName": SCHOOL_NAME,
        "admin": admin_user.email,
        "senco": senco_user.email,
        "students": len(students),
        "consent": consent_counts,
        "classes": len(CLASSES),
        "teacherAssignments": assignments,
        "attentionFlags": TOTAL_FLAGS,
        "flagsAcknowledged": acknowledged,
        "flaggedStudents": FLAGGED_STUDENTS,
        "adaptationEvents": ADAPTATION_EVENTS,
        "adaptationStudents": ADAPTATION_STUDENTS,
        "syncRuns": len(runs),
        "syncIssues": issue_count,
        "invoices": {"paid": paid.invoice_number, "unpaid": unpaid.invoice_number},
        "contractSeeded": tier_id is not None,
    }


async def main() -> None:
    engine = create_async_engine(database_url())
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker.begin() as session:
        summary = await seed(session)
    await engine.dispose()
    import json

    Path("backups/e2e-tenant-summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
