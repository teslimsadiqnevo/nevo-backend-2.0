from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import NAMESPACE_DNS, UUID, uuid5

from sqlalchemy import select

from nevo.auth.config import AuthSettings
from nevo.auth.wiring import build_credential_hasher
from nevo.core.config import get_settings
from nevo.db.models.account import Class, School, StudentClassEnrollment, User
from nevo.db.models.content import ContentParseRun, Lesson, LessonSegment
from nevo.db.models.frontend_support import (
    Concept,
    LessonAssignment,
    Message,
    MessageThread,
    Notification,
)
from nevo.db.models.mastery import (
    ScaffoldProblemLog,
    StudentConceptMastery,
    StudentConceptScaffoldState,
    StudentConceptScheduling,
)
from nevo.db.models.signal_event import LessonSession
from nevo.db.models.teacher_assignment import TeacherClassAssignment
from nevo.db.session import create_engine, create_session_factory
from nevo.domain.accounts.vocabulary import AuthMethod, UserRole, UserStatus
from nevo.domain.billing.vocabulary import SubscriptionTier
from nevo.domain.intelligence.vocabulary import (
    ContentModality,
    ContentParseStatus,
    LessonContentType,
    LessonSourceType,
    ScaffoldIntensity,
    ScaffoldOutcome,
)
from nevo.domain.mastery.vocabulary import FailureAttribution
from nevo.domain.signal_events.vocabulary import LessonCompletionStatus
from nevo.domain.teacher_assignments.vocabulary import (
    TeacherAssignmentRole,
    TeacherAssignmentSource,
)

TEACHER_EMAIL = "teacher.demo@nevolearning.com"
ADMIN_EMAIL = "admin.demo@nevolearning.com"
SCHOOL_CODE = "NEVO-DEMO"


def stable_id(key: str) -> UUID:
    return uuid5(NAMESPACE_DNS, f"nevo-demo:{key}")


async def main() -> None:
    engine = create_engine(get_settings().database_url)
    sessions = create_session_factory(engine)
    hasher = build_credential_hasher(AuthSettings())
    try:
        async with sessions.begin() as session:
            school = await session.scalar(
                select(School).where(School.school_code == SCHOOL_CODE)
            )
            if school is None:
                school = School(
                    id=stable_id("school"),
                    name="Nevo Demo School",
                    school_code=SCHOOL_CODE,
                    school_url_slug="nevo-demo",
                    auth_method=AuthMethod.EMAIL_PASSWORD,
                    subscription_tier=SubscriptionTier.MID_MARKET,
                    contract_value=Decimal("50000.00"),
                )
                session.add(school)
                await session.flush()

            teacher = await session.scalar(
                select(User).where(User.email == TEACHER_EMAIL)
            )
            if teacher is None:
                raise SystemExit("teacher.demo@nevolearning.com does not exist")
            teacher.school_id = school.id
            teacher.role = UserRole.TEACHER
            teacher.status = UserStatus.ACTIVE
            teacher.first_name = teacher.first_name or "Tunde"
            teacher.last_name = teacher.last_name or "Adebayo"
            if teacher_password := os.getenv("NEVO_DEMO_TEACHER_PASSWORD"):
                teacher.password_hash = hasher.hash_password(teacher_password)

            admin = await session.scalar(select(User).where(User.email == ADMIN_EMAIL))
            if admin is not None:
                admin.school_id = school.id
                admin.status = UserStatus.ACTIVE
                if admin_password := os.getenv("NEVO_DEMO_ADMIN_PASSWORD"):
                    admin.password_hash = hasher.hash_password(admin_password)

            school_class = await _get_or_create(
                session,
                Class,
                stable_id("jss-2a"),
                school_id=school.id,
                name="JSS 2A",
                class_code="JSS2A",
            )
            await _get_or_create(
                session,
                TeacherClassAssignment,
                stable_id("teacher-jss-2a"),
                school_id=school.id,
                teacher_id=teacher.id,
                class_id=school_class.id,
                role=TeacherAssignmentRole.PRIMARY,
                source=TeacherAssignmentSource.MANUAL,
                assigned_by_user_id=admin.id if admin else teacher.id,
            )

            students = [
                await _student(
                    session,
                    school.id,
                    "amara.demo",
                    "Amara",
                    "Okafor",
                ),
                await _student(session, school.id, "kofi.demo", "Kofi", "Dada"),
                await _student(session, school.id, "dara.demo", "Dara", "Ibrahim"),
            ]
            if student_pin := os.getenv("NEVO_DEMO_STUDENT_PIN"):
                for student in students:
                    student.pin_hash = hasher.hash_pin(student_pin)
            for student in students:
                await _get_or_create(
                    session,
                    StudentClassEnrollment,
                    stable_id(f"enroll:{student.login_identifier}"),
                    student_id=student.id,
                    class_id=school_class.id,
                )

            lesson = await _get_or_create(
                session,
                Lesson,
                stable_id("fractions-lesson-3"),
                school_id=school.id,
                created_by_user_id=teacher.id,
                title="Fractions Lesson 3",
                source_type=LessonSourceType.TEXT,
                source_reference={"seed": "demo_teacher_console"},
                status=ContentParseStatus.COMPLETED_WITH_REVIEW,
                segment_count=2,
                review_segment_count=0,
                confirmation_summary="Demo lesson seeded for teacher console testing.",
            )
            await _get_or_create(
                session,
                ContentParseRun,
                stable_id("parse-run:fractions-lesson-3"),
                lesson_id=lesson.id,
                requested_by_user_id=teacher.id,
                status=ContentParseStatus.COMPLETED_WITH_REVIEW,
                source_type=LessonSourceType.TEXT,
                source_metadata={"seed": "demo_teacher_console"},
                chunk_count=1,
                gemini_call_count=0,
                calculation_segment_count=0,
                tts_call_count=0,
                review_notes=[],
                completed_at=datetime.now(UTC),
            )
            await _lesson_segment(session, lesson.id, 1, "Equal parts of a whole")
            await _lesson_segment(session, lesson.id, 2, "Adding simple fractions")

            concept_specs = [
                ("fractions", "Fractions", 0.68, 0.74),
                ("equivalent-fractions", "Equivalent fractions", 0.56, 0.66),
                ("adding-fractions", "Adding fractions", 0.61, 0.70),
            ]
            concepts = []
            for key, name, _, _ in concept_specs:
                concepts.append(
                    await _get_or_create(
                        session,
                        Concept,
                        stable_id(f"concept:{key}"),
                        school_id=school.id,
                        name=name,
                        subject="Mathematics",
                        source="demo_seed",
                    )
                )

            now = datetime.now(UTC)
            for index, student in enumerate(students):
                for concept, (_, _, concept_score, reading_score) in zip(
                    concepts,
                    concept_specs,
                    strict=True,
                ):
                    await _get_or_create(
                        session,
                        StudentConceptMastery,
                        stable_id(f"mastery:{student.id}:{concept.id}"),
                        student_id=student.id,
                        concept_id=concept.id,
                        mastery_probability_concept=max(
                            0.1,
                            concept_score - index * 0.04,
                        ),
                        mastery_probability_reading=max(
                            0.1,
                            reading_score - index * 0.03,
                        ),
                        attention_weights={},
                        guess_probability=0.2,
                        slip_probability=0.1,
                        practice_count=4 + index,
                        last_response_correct=index != 1,
                        last_failure_attribution=FailureAttribution.NONE,
                        seeding_source="demo_seed",
                    )
                    await _get_or_create(
                        session,
                        StudentConceptScheduling,
                        stable_id(f"scheduling:{student.id}:{concept.id}"),
                        student_id=student.id,
                        concept_id=concept.id,
                        stability=2.0,
                        difficulty=4.0,
                        last_review=now - timedelta(days=2 + index),
                        review_count=2 + index,
                        next_review_due=now - timedelta(hours=1),
                    )
                await _get_or_create(
                    session,
                    StudentConceptScaffoldState,
                    stable_id(f"scaffold-state:{student.id}:{concepts[0].id}"),
                    student_id=student.id,
                    concept_id=concepts[0].id,
                    current_intensity=ScaffoldIntensity.PARTIAL_SUPPORT,
                    consecutive_correct=2,
                    response_time_improvement_streak=1,
                    reduced_hint_streak=1,
                    last_response_time_ms=4200,
                    last_hint_count=1,
                )
                await _get_or_create(
                    session,
                    ScaffoldProblemLog,
                    stable_id(f"scaffold-log:{student.id}:1"),
                    student_id=student.id,
                    concept_id=concepts[0].id,
                    problem_id="demo-problem-1",
                    scaffold_intensity=ScaffoldIntensity.FULL_SUPPORT,
                    outcome=ScaffoldOutcome.CORRECT,
                    response_time_ms=4800,
                    expected_response_time_ms=6000,
                    hint_count=1,
                    next_scaffold_intensity=ScaffoldIntensity.PARTIAL_SUPPORT,
                    level_changed=True,
                    change_reason="Three aligned mastery signals supported fading.",
                )
                await _get_or_create(
                    session,
                    LessonSession,
                    stable_id(f"lesson-session:{student.id}"),
                    student_id=student.id,
                    lesson_id=lesson.id,
                    started_at=now - timedelta(hours=2, minutes=index * 10),
                    completion_status=LessonCompletionStatus.COMPLETED,
                    exit_position="complete",
                    break_count=index,
                    proactive_adjustments_count=1,
                )
                await _get_or_create(
                    session,
                    LessonAssignment,
                    stable_id(f"assignment:{student.id}:{lesson.id}"),
                    lesson_id=lesson.id,
                    student_id=student.id,
                    teacher_id=teacher.id,
                    class_id=school_class.id,
                    assignment_type="class",
                    status="assigned",
                    due_at=now + timedelta(days=7),
                )

            await _get_or_create(
                session,
                Notification,
                stable_id("teacher-notification-1"),
                recipient_id=teacher.id,
                recipient_role="teacher",
                type="attention_summary",
                title="JSS 2A has fresh lesson activity",
                description="Three students have recent fraction practice to review.",
                navigates_to="/teacher/classes",
                read=False,
            )
            thread = await _get_or_create(
                session,
                MessageThread,
                stable_id("thread-amara"),
                school_id=school.id,
                recipient_type="student",
                student_id=students[0].id,
                class_id=None,
                created_by_id=teacher.id,
                latest_preview="Great work on the fraction examples today.",
                last_message_at=now,
            )
            await _get_or_create(
                session,
                Message,
                stable_id("message-amara-1"),
                thread_id=thread.id,
                sender_id=teacher.id,
                content="Great work on the fraction examples today.",
            )

        print("Demo teacher console seed complete.")
    finally:
        await engine.dispose()


async def _student(session, school_id: UUID, login: str, first: str, last: str) -> User:
    user = await session.scalar(
        select(User).where(User.school_id == school_id, User.login_identifier == login)
    )
    if user is None:
        user = User(
            id=stable_id(f"student:{login}"),
            school_id=school_id,
            role=UserRole.STUDENT,
            auth_method=AuthMethod.PIN,
            first_name=first,
            last_name=last,
            login_identifier=login,
            status=UserStatus.ACTIVE,
        )
        session.add(user)
        await session.flush()
    else:
        user.school_id = school_id
        user.first_name = user.first_name or first
        user.last_name = user.last_name or last
        user.status = UserStatus.ACTIVE
    return user


async def _lesson_segment(session, lesson_id: UUID, order: int, title: str) -> None:
    existing = await session.scalar(
        select(LessonSegment).where(
            LessonSegment.lesson_id == lesson_id,
            LessonSegment.sequence_order == order,
        )
    )
    if existing is not None:
        return
    segment = LessonSegment(
        id=stable_id(f"segment:{lesson_id}:{order}"),
        lesson_id=lesson_id,
        parse_run_id=stable_id("parse-run:fractions-lesson-3"),
        segment_key=f"segment-{order}",
        content_type=LessonContentType.EXPLANATORY_TEXT,
        sequence_order=order,
        title=title,
        body=(
            "Fractions help us talk about equal parts. "
            "Use the numerator for selected parts and denominator for total parts."
        ),
        available_modalities=[ContentModality.TEXT.value, ContentModality.VISUAL.value],
        comprehension_checkpoints=[],
        needs_review=False,
        review_reasons=[],
    )
    session.add(segment)


async def _get_or_create(session, model, item_id: UUID, **values):
    item = await session.get(model, item_id)
    if item is not None:
        return item
    item = model(id=item_id, **values)
    session.add(item)
    await session.flush()
    return item


if __name__ == "__main__":
    asyncio.run(main())
