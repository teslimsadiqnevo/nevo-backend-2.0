"""Which lessons a teacher is shown, against real Postgres, rolled back.

The rule spans four tables, so an in-memory double would be asserting its own
behaviour rather than the query's.
"""
import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from nevo.access import accessible_lessons
from nevo.core.config import get_settings
from nevo.db.models.account import Class, School, StudentClassEnrollment, User
from nevo.db.models.content import Lesson
from nevo.db.models.frontend_support import LessonAssignment
from nevo.db.models.teacher_assignment import TeacherClassAssignment
from nevo.db.session import create_engine
from nevo.domain.accounts.vocabulary import AuthMethod, UserRole, UserStatus
from nevo.domain.intelligence.vocabulary import (
    ContentParseStatus,
    LessonScope,
    LessonSourceType,
)
from nevo.domain.teacher_assignments.vocabulary import (
    TeacherAssignmentRole,
    TeacherAssignmentSource,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL"),
        reason="TEST_DATABASE_URL is required for PostgreSQL integration tests",
    ),
]


class World:
    """One school: two teachers, a class, and four lessons between them."""

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        self.session = session

    async def build(self) -> None:
        token = uuid.uuid4().hex[:12]
        school = School(
            name="Lesson Scope School",
            school_code=f"ls-{token}",
            school_url_slug=f"ls-{token}",
        )
        self.session.add(school)
        await self.session.flush()

        def person(role: UserRole) -> User:
            user = User(
                school_id=school.id,
                role=role,
                auth_method=AuthMethod.PIN,
                status=UserStatus.ACTIVE,
            )
            self.session.add(user)
            return user

        self.mine = person(UserRole.TEACHER)
        self.colleague = person(UserRole.TEACHER)
        self.admin = person(UserRole.OTHER_ADMIN)
        self.learner = person(UserRole.STUDENT)
        await self.session.flush()

        self.taught = Class(school_id=school.id, name=f"Taught {token}")
        self.session.add(self.taught)
        await self.session.flush()
        self.session.add(
            TeacherClassAssignment(
                school_id=school.id,
                teacher_id=self.mine.id,
                class_id=self.taught.id,
                role=TeacherAssignmentRole.PRIMARY,
                source=TeacherAssignmentSource.MANUAL,
                assigned_at=datetime.now(UTC),
            )
        )
        self.session.add(
            StudentClassEnrollment(student_id=self.learner.id, class_id=self.taught.id)
        )

        def lesson(title: str, author: User) -> Lesson:
            item = Lesson(
                school_id=school.id,
                created_by_user_id=author.id,
                title=title,
                source_type=LessonSourceType.TEXT,
                parser_version=1,
                status=ContentParseStatus.COMPLETED,
                segment_count=1,
                review_segment_count=0,
                estimated_minutes=5,
            )
            self.session.add(item)
            return item

        self.authored = lesson("Authored by me", self.mine)
        self.assigned_by_me = lesson("Someone else wrote, I assign", self.colleague)
        self.taught_class = lesson("Assigned to my class", self.colleague)
        self.unrelated = lesson("Nothing to do with me", self.colleague)
        await self.session.flush()

        self.session.add(
            LessonAssignment(
                lesson_id=self.assigned_by_me.id,
                student_id=self.learner.id,
                teacher_id=self.mine.id,
                assignment_type="individual",
                status="assigned",
            )
        )
        self.session.add(
            LessonAssignment(
                lesson_id=self.taught_class.id,
                student_id=self.learner.id,
                teacher_id=self.colleague.id,
                class_id=self.taught.id,
                assignment_type="class",
                status="assigned",
            )
        )
        self.session.add(
            LessonAssignment(
                lesson_id=self.unrelated.id,
                student_id=self.learner.id,
                teacher_id=self.colleague.id,
                assignment_type="individual",
                status="cancelled",
            )
        )
        await self.session.flush()


async def in_rollback(check):  # type: ignore[no-untyped-def]
    engine = create_engine(get_settings().database_url)
    connection = await engine.connect()
    transaction = await connection.begin()
    try:
        sessions = async_sessionmaker(bind=connection, expire_on_commit=False)
        async with sessions() as session:
            world = World(session)
            await world.build()
            return await check(session, world)
    finally:
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


async def test_a_teacher_defaults_to_the_lessons_that_are_theirs() -> None:
    async def check(session, world):  # type: ignore[no-untyped-def]
        return {
            lesson.title
            for lesson in await accessible_lessons(session, world.mine)
        }

    titles = await in_rollback(check)

    assert titles == {
        "Authored by me",
        "Someone else wrote, I assign",
        "Assigned to my class",
    }
    assert "Nothing to do with me" not in titles


async def test_a_teacher_can_still_ask_for_the_whole_school() -> None:
    """The shared library is worth browsing; it just is not the default."""

    async def check(session, world):  # type: ignore[no-untyped-def]
        return {
            lesson.title
            for lesson in await accessible_lessons(
                session, world.mine, scope=LessonScope.SCHOOL
            )
        }

    assert "Nothing to do with me" in await in_rollback(check)


async def test_an_administrator_oversees_the_whole_school_by_default() -> None:
    async def check(session, world):  # type: ignore[no-untyped-def]
        return len(await accessible_lessons(session, world.admin))

    assert await in_rollback(check) == 4


async def test_a_learner_sees_what_was_assigned_and_not_what_was_cancelled() -> None:
    async def check(session, world):  # type: ignore[no-untyped-def]
        return {
            lesson.title
            for lesson in await accessible_lessons(session, world.learner)
        }

    titles = await in_rollback(check)

    assert titles == {"Someone else wrote, I assign", "Assigned to my class"}


async def test_a_learner_cannot_widen_their_own_view() -> None:
    """scope is a teacher's convenience, not a way past assignment."""

    async def check(session, world):  # type: ignore[no-untyped-def]
        return {
            lesson.title
            for lesson in await accessible_lessons(
                session, world.learner, scope=LessonScope.SCHOOL
            )
        }

    assert "Nothing to do with me" not in await in_rollback(check)
