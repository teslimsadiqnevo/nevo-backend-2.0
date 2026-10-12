"""The one student CI signs in as, with a handle that never changes.

Everything else in the E2E tenant is generated, so its identifiers move every
time it is rebuilt - which is correct for data meant to exercise thresholds,
and useless for a test that has to sign in as somebody. This is the fixed
point: one child, one handle, written down in docs/test-tenant-spec.md and
safe to put in CI. Ask B66.

Idempotent. Run it after seed_e2e_tenant.py, or on its own against an
existing tenant.

Usage:
    .venv/bin/python scripts/seed_e2e_probe_student.py
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import NAMESPACE_DNS, UUID, uuid5

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nevo.api.product_auth import credential_hasher
from nevo.db.models.account import (
    Class,
    ConsentRecord,
    School,
    StudentClassEnrollment,
    User,
)
from nevo.db.models.attention_flag import AttentionFlag, InterventionRecommendation
from nevo.db.models.content import ContentParseRun, Lesson, LessonSegment
from nevo.db.models.frontend_support import LessonAssignment, Message, MessageThread
from nevo.db.models.permission import Admin, AdminScopeAssignment
from nevo.db.models.teacher_assignment import TeacherClassAssignment
from nevo.domain.accounts.age_bands import band_for_date_of_birth
from nevo.domain.accounts.vocabulary import (
    AuthMethod,
    ConsentStatus,
    UserRole,
    UserStatus,
)
from nevo.domain.attention_flags.vocabulary import AttentionFlagType
from nevo.domain.consent.vocabulary import REQUIRED_LEARNING_CONSENT
from nevo.domain.intelligence.vocabulary import (
    ContentParseStatus,
    LessonContentType,
    LessonSourceType,
)
from nevo.domain.permissions.vocabulary import PermissionScope

#: The handle CI signs in with. Fixed by agreement, not generated.
LOGIN_IDENTIFIER = "NV-E2E000"
ADMISSION_NUMBER = "E2E/PROBE"
PIN = "4820"
BORN = date(2014, 9, 1)

#: Consent is given, so the probe student can actually reach a lesson. A
#: child the tests cannot get past the consent gate is a child the tests
#: cannot use.
CONSENT = ConsentStatus.CONFIRMED


def fixture_id(name: str) -> UUID:
    return uuid5(NAMESPACE_DNS, f"nevo-e2e-write:{name}")


async def seed_write_fixtures(session, school: School, student: User, school_class: Class) -> None:
    teacher = await session.scalar(
        select(User)
        .join(TeacherClassAssignment, TeacherClassAssignment.teacher_id == User.id)
        .where(
            TeacherClassAssignment.class_id == school_class.id,
            TeacherClassAssignment.removed_at.is_(None),
            User.status == UserStatus.ACTIVE,
        )
        .order_by(User.id)
    )
    if teacher is None:
        teacher = await session.scalar(
            select(User)
            .where(
                User.school_id == school.id,
                User.role == UserRole.TEACHER,
                User.status == UserStatus.ACTIVE,
            )
            .order_by(User.id)
        )
    if teacher is None:
        raise SystemExit("No teacher on the E2E tenant for write fixtures.")

    now = datetime.now(UTC)
    lessons: list[tuple[Lesson, bool]] = []
    for suffix, title, needs_review in (
        ("assignable", "E2E Reversible Assignment", False),
        ("review", "E2E Reversible Approval", True),
        ("new-assignment", "E2E Reversible New Assignment", False),
    ):
        lesson_id = fixture_id(f"lesson:{suffix}")
        lesson = await session.get(Lesson, lesson_id)
        if lesson is None:
            lesson = Lesson(id=lesson_id, created_by_user_id=teacher.id)
            session.add(lesson)
        lesson.school_id = school.id
        lesson.title = title
        lesson.description = "Deterministic CI fixture. The seed restores its state."
        lesson.subject = "Mathematics"
        lesson.source_type = LessonSourceType.TEXT
        lesson.status = (
            ContentParseStatus.COMPLETED_WITH_REVIEW
            if needs_review
            else ContentParseStatus.COMPLETED
        )
        lesson.segment_count = 1
        lesson.review_segment_count = int(needs_review)
        lesson.estimated_minutes = 5
        await session.flush()

        run_id = fixture_id(f"parse:{suffix}")
        run = await session.get(ContentParseRun, run_id)
        if run is None:
            run = ContentParseRun(
                id=run_id,
                lesson_id=lesson.id,
                requested_by_user_id=teacher.id,
                source_type=LessonSourceType.TEXT,
            )
            session.add(run)
        run.status = lesson.status
        run.completed_at = now
        run.review_notes = []
        await session.flush()

        segment_id = fixture_id(f"segment:{suffix}")
        segment = await session.get(LessonSegment, segment_id)
        if segment is None:
            segment = LessonSegment(
                id=segment_id,
                lesson_id=lesson.id,
                parse_run_id=run.id,
                segment_key=f"e2e-{suffix}",
                content_type=LessonContentType.EXPLANATORY_TEXT,
                sequence_order=1,
                body="A stable section used only by end-to-end write tests.",
                available_modalities=["text"],
            )
            session.add(segment)
        segment.title = "E2E section"
        segment.needs_review = needs_review
        segment.review_reasons = ["e2e approval fixture"] if needs_review else []
        segment.approved_at = None if needs_review else now
        segment.approved_by = None if needs_review else teacher.id
        lessons.append((lesson, needs_review))

    assignment_id = fixture_id("assignment:cancel")
    assignment = await session.get(LessonAssignment, assignment_id)
    if assignment is None:
        assignment = LessonAssignment(
            id=assignment_id,
            lesson_id=lessons[0][0].id,
            student_id=student.id,
            teacher_id=teacher.id,
        )
        session.add(assignment)
    assignment.class_id = school_class.id
    assignment.assignment_type = "student"
    assignment.status = "assigned"
    assignment.cancellation_reason = None
    assignment.recall_withdrawn = False

    thread_id = fixture_id("message-thread")
    thread = await session.get(MessageThread, thread_id)
    if thread is None:
        thread = MessageThread(
            id=thread_id,
            school_id=school.id,
            recipient_type="student",
            student_id=student.id,
            created_by_id=teacher.id,
        )
        session.add(thread)
    thread.class_id = school_class.id
    thread.latest_preview = "E2E thread ready for a reversible message"
    thread.last_message_at = now
    await session.execute(delete(Message).where(Message.thread_id == thread.id))

    flag_id = fixture_id("attention-flag")
    flag = await session.get(AttentionFlag, flag_id)
    if flag is None:
        flag = AttentionFlag(
            id=flag_id,
            student_id=student.id,
            flag_type=AttentionFlagType.ENGAGEMENT_DECLINE,
            description="Recent lesson participation has been quieter than this learner's pattern.",
        )
        session.add(flag)
    flag.acknowledged_at = None
    flag.acknowledged_by = None
    flag.evidence_series = [0.82, 0.71, 0.58]
    flag.action_targets = ["view_student", "open_recommendation"]
    await session.flush()

    recommendation_id = fixture_id("recommendation")
    recommendation = await session.get(InterventionRecommendation, recommendation_id)
    if recommendation is None:
        recommendation = InterventionRecommendation(
            id=recommendation_id,
            attention_flag_id=flag.id,
            student_id=student.id,
            recommendation_text="Try the short fractions recap before the next activity.",
        )
        session.add(recommendation)
    recommendation.lesson_id = lessons[0][0].id

    print(f"writeFixtureAssignment={assignment.id}")
    print(f"writeFixtureAssignableLesson={lessons[2][0].id}")
    print(f"writeFixtureReviewLesson={lessons[1][0].id}")
    print(f"writeFixtureThread={thread.id}")
    print(f"writeFixtureFlag={flag.id}")
    print(f"writeFixtureRecommendation={recommendation.id}")


def database_url() -> str:
    for line in Path(".env").read_text().splitlines():
        match = re.match(r"\s*DATABASE_URL\s*=\s*(.+)", line)
        if match:
            raw = match.group(1).strip().strip('"').strip("'")
            raw = raw.replace("postgresql://", "postgresql+asyncpg://")
            return re.sub(r"[?&]sslmode=\w+", "", raw)
    raise SystemExit("DATABASE_URL not found in .env")


async def main() -> None:
    engine = create_async_engine(database_url())
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker.begin() as session:
        school = await session.scalar(select(School).where(School.name.ilike("E2E Test Academy%")))
        if school is None:
            raise SystemExit("No E2E tenant. Run seed_e2e_tenant.py first.")
        admin = await session.scalar(
            select(Admin).where(Admin.school_id == school.id).order_by(Admin.id)
        )
        if admin is None:
            raise SystemExit("No administrator on the E2E tenant.")
        active_scopes = set(
            await session.scalars(
                select(AdminScopeAssignment.scope).where(
                    AdminScopeAssignment.admin_id == admin.id,
                    AdminScopeAssignment.revoked_at.is_(None),
                )
            )
        )
        for scope in PermissionScope:
            if scope not in active_scopes:
                session.add(
                    AdminScopeAssignment(
                        admin_id=admin.id,
                        scope=scope,
                        granted_by_user_id=admin.user_id,
                    )
                )
        student = await session.scalar(
            select(User).where(User.login_identifier == LOGIN_IDENTIFIER)
        )
        school_class = await session.scalar(
            select(Class)
            .where(Class.school_id == school.id, Class.archived_at.is_(None))
            .order_by(Class.name)
        )
        if student is None:
            student = User(
                school_id=school.id,
                role=UserRole.STUDENT,
                auth_method=AuthMethod.PIN,
                first_name="Probe",
                last_name="Student",
                admission_number=ADMISSION_NUMBER,
                login_identifier=LOGIN_IDENTIFIER,
                date_of_birth=BORN,
                age_band=band_for_date_of_birth(BORN),
                pin_hash=credential_hasher().hash_pin(PIN),
                status=UserStatus.ACTIVE,
            )
            session.add(student)
            await session.flush()
            if school_class is not None:
                session.add(StudentClassEnrollment(student_id=student.id, class_id=school_class.id))
            now = datetime.now(UTC)
            session.add(
                ConsentRecord(
                    subject_user_id=student.id,
                    consent_type=REQUIRED_LEARNING_CONSENT,
                    status=CONSENT,
                    confirmation_source="school",
                    confirmed_by_admin_id=admin.user_id,
                    confirmed_at=now,
                    confirmed_via="email",
                    last_changed_at=now,
                    last_channel="email",
                )
            )
        if school_class is None:
            raise SystemExit("No class on the E2E tenant for write fixtures.")
        await seed_write_fixtures(session, school, student, school_class)
        print(f"schoolCode={school.school_code}")
        print(f"loginIdentifier={LOGIN_IDENTIFIER}")
        print(f"admissionNumber={ADMISSION_NUMBER}")
        print(f"pin={PIN}")
        print(f"class={school_class.name if school_class else 'none'}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
