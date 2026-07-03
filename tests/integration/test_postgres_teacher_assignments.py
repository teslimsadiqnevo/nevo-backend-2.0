import os
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from nevo.db.session import create_engine, create_session_factory
from nevo.domain.teacher_assignments.vocabulary import (
    TeacherAssignmentRole,
    TeacherAssignmentSource,
)
from nevo.teacher_assignments.errors import TeacherNotFoundError
from nevo.teacher_assignments.repositories import (
    SqlAlchemyTeacherAssignmentRepository,
)

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason="TEST_DATABASE_URL is required for PostgreSQL integration tests",
    ),
]


def asyncpg_url() -> str:
    assert TEST_DATABASE_URL is not None
    return TEST_DATABASE_URL.replace(
        "postgresql+asyncpg://",
        "postgresql://",
        1,
    )


async def create_school(connection: asyncpg.Connection) -> uuid.UUID:
    token = uuid.uuid4().hex[:12]
    school_id = await connection.fetchval(
        """
        INSERT INTO schools (name, school_code, school_url_slug)
        VALUES ('Teacher Assignment Test School', $1, $2)
        RETURNING id
        """,
        f"assignment-{token}",
        f"assignment-{token}",
    )
    assert isinstance(school_id, uuid.UUID)
    return school_id


async def create_user(
    connection: asyncpg.Connection,
    *,
    school_id: uuid.UUID,
    role: str = "teacher",
) -> uuid.UUID:
    token = uuid.uuid4().hex[:12]
    user_id = await connection.fetchval(
        """
        INSERT INTO users (
            school_id,
            role,
            auth_method,
            first_name,
            last_name,
            email
        )
        VALUES ($1, $2, 'email_password', 'Test', 'Teacher', $3)
        RETURNING id
        """,
        school_id,
        role,
        f"{token}@example.com",
    )
    assert isinstance(user_id, uuid.UUID)
    return user_id


async def create_class(
    connection: asyncpg.Connection,
    *,
    school_id: uuid.UUID,
) -> uuid.UUID:
    token = uuid.uuid4().hex[:10]
    class_id = await connection.fetchval(
        """
        INSERT INTO classes (school_id, name, class_code)
        VALUES ($1, 'JSS 3', $2)
        RETURNING id
        """,
        school_id,
        f"J3-{token}",
    )
    assert isinstance(class_id, uuid.UUID)
    return class_id


async def repository() -> tuple[
    SqlAlchemyTeacherAssignmentRepository,
    object,
]:
    assert TEST_DATABASE_URL is not None
    engine = create_engine(TEST_DATABASE_URL)
    return (
        SqlAlchemyTeacherAssignmentRepository(
            create_session_factory(engine),
        ),
        engine,
    )


async def test_database_enforces_one_active_primary_per_class() -> None:
    connection = await asyncpg.connect(asyncpg_url())
    try:
        school_id = await create_school(connection)
        teacher_one = await create_user(
            connection,
            school_id=school_id,
        )
        teacher_two = await create_user(
            connection,
            school_id=school_id,
        )
        class_id = await create_class(connection, school_id=school_id)
        await connection.execute(
            """
            INSERT INTO teacher_class_assignments (
                school_id,
                teacher_id,
                class_id,
                role
            )
            VALUES ($1, $2, $3, 'primary')
            """,
            school_id,
            teacher_one,
            class_id,
        )

        with pytest.raises(asyncpg.UniqueViolationError):
            await connection.execute(
                """
                INSERT INTO teacher_class_assignments (
                    school_id,
                    teacher_id,
                    class_id,
                    role
                )
                VALUES ($1, $2, $3, 'primary')
                """,
                school_id,
                teacher_two,
                class_id,
            )
    finally:
        await connection.close()


async def test_repository_reassignment_preserves_history() -> None:
    connection = await asyncpg.connect(asyncpg_url())
    try:
        school_id = await create_school(connection)
        teacher_one = await create_user(
            connection,
            school_id=school_id,
        )
        teacher_two = await create_user(
            connection,
            school_id=school_id,
        )
        class_id = await create_class(connection, school_id=school_id)
    finally:
        await connection.close()

    assignment_repository, engine = await repository()
    assigned_at = datetime.now(UTC)
    replacement_at = assigned_at + timedelta(minutes=5)
    try:
        original = await assignment_repository.assign(
            school_id=school_id,
            teacher_id=teacher_one,
            class_id=class_id,
            role=TeacherAssignmentRole.PRIMARY,
            source=TeacherAssignmentSource.MANUAL,
            source_reference=None,
            assigned_by_user_id=teacher_one,
            assigned_at=assigned_at,
        )
        replacement = await assignment_repository.reassign(
            school_id=school_id,
            assignment_id=original.id,
            new_teacher_id=teacher_two,
            role=None,
            assigned_by_user_id=teacher_one,
            assigned_at=replacement_at,
        )
        teacher_classes = await assignment_repository.teacher_classes(
            school_id=school_id,
            teacher_id=teacher_two,
        )
        is_old_teacher_assigned = (
            await assignment_repository.is_teacher_assigned(
                school_id=school_id,
                teacher_id=teacher_one,
                class_id=class_id,
            )
        )
    finally:
        await engine.dispose()

    connection = await asyncpg.connect(asyncpg_url())
    try:
        old_row = await connection.fetchrow(
            """
            SELECT removed_at, replaced_by_assignment_id
            FROM teacher_class_assignments
            WHERE id = $1
            """,
            original.id,
        )
        active_count = await connection.fetchval(
            """
            SELECT count(*)
            FROM teacher_class_assignments
            WHERE class_id = $1 AND removed_at IS NULL
            """,
            class_id,
        )
    finally:
        await connection.close()

    assert replacement.teacher_id == teacher_two
    assert replacement.role is TeacherAssignmentRole.PRIMARY
    assert old_row is not None
    assert old_row["removed_at"] == replacement_at
    assert old_row["replaced_by_assignment_id"] == replacement.id
    assert active_count == 1
    assert not is_old_teacher_assigned
    assert [item.class_id for item in teacher_classes] == [class_id]


async def test_repository_rejects_teacher_from_another_school() -> None:
    connection = await asyncpg.connect(asyncpg_url())
    try:
        school_id = await create_school(connection)
        other_school_id = await create_school(connection)
        other_teacher_id = await create_user(
            connection,
            school_id=other_school_id,
        )
        class_id = await create_class(connection, school_id=school_id)
    finally:
        await connection.close()

    assignment_repository, engine = await repository()
    try:
        with pytest.raises(TeacherNotFoundError):
            await assignment_repository.assign(
                school_id=school_id,
                teacher_id=other_teacher_id,
                class_id=class_id,
                role=TeacherAssignmentRole.CO_TEACHER,
                source=TeacherAssignmentSource.MANUAL,
                source_reference=None,
                assigned_by_user_id=None,
                assigned_at=datetime.now(UTC),
            )
    finally:
        await engine.dispose()
