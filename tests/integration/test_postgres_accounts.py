import os
import uuid

import asyncpg
import pytest

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
    return TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)


async def create_school(connection: asyncpg.Connection) -> uuid.UUID:
    token = uuid.uuid4().hex[:12]
    school_id = await connection.fetchval(
        """
        INSERT INTO schools (name, school_code, school_url_slug)
        VALUES ($1, $2, $3)
        RETURNING id
        """,
        "Test School",
        f"code-{token}",
        f"slug-{token}",
    )
    assert isinstance(school_id, uuid.UUID)
    return school_id


async def create_user(
    connection: asyncpg.Connection,
    *,
    role: str = "student",
    auth_method: str = "pin",
) -> uuid.UUID:
    user_id = await connection.fetchval(
        """
        INSERT INTO users (role, auth_method)
        VALUES ($1, $2)
        RETURNING id
        """,
        role,
        auth_method,
    )
    assert isinstance(user_id, uuid.UUID)
    return user_id


async def test_school_code_is_unique() -> None:
    connection = await asyncpg.connect(asyncpg_url())
    token = uuid.uuid4().hex[:12]
    try:
        await connection.execute(
            "INSERT INTO schools (name, school_code, school_url_slug) VALUES ($1, $2, $3)",
            "A",
            f"code-{token}",
            f"slug-a-{token}",
        )
        with pytest.raises(asyncpg.UniqueViolationError):
            await connection.execute(
                "INSERT INTO schools (name, school_code, school_url_slug) VALUES ($1, $2, $3)",
                "B",
                f"code-{token}",
                f"slug-b-{token}",
            )
    finally:
        await connection.close()


async def test_active_user_cannot_have_deactivated_at() -> None:
    connection = await asyncpg.connect(asyncpg_url())
    try:
        with pytest.raises(asyncpg.CheckViolationError):
            await connection.execute(
                """
                INSERT INTO users (role, auth_method, status, deactivated_at)
                VALUES ('student', 'pin', 'active', now())
                """
            )
    finally:
        await connection.close()


async def test_deactivated_user_requires_deactivated_at() -> None:
    connection = await asyncpg.connect(asyncpg_url())
    try:
        with pytest.raises(asyncpg.CheckViolationError):
            await connection.execute(
                """
                INSERT INTO users (role, auth_method, status, deactivated_at)
                VALUES ('student', 'pin', 'deactivated', NULL)
                """
            )
    finally:
        await connection.close()


async def test_enrollment_is_unique_per_student_and_class() -> None:
    connection = await asyncpg.connect(asyncpg_url())
    try:
        school_id = await create_school(connection)
        student_id = await create_user(connection)
        class_id = await connection.fetchval(
            "INSERT INTO classes (school_id, name) VALUES ($1, $2) RETURNING id",
            school_id,
            "Class 1",
        )
        await connection.execute(
            "INSERT INTO student_class_enrollments (student_id, class_id) VALUES ($1, $2)",
            student_id,
            class_id,
        )
        with pytest.raises(asyncpg.UniqueViolationError):
            await connection.execute(
                "INSERT INTO student_class_enrollments (student_id, class_id) VALUES ($1, $2)",
                student_id,
                class_id,
            )
    finally:
        await connection.close()


async def test_confirmed_consent_requires_confirmation_fields() -> None:
    connection = await asyncpg.connect(asyncpg_url())
    try:
        subject_id = await create_user(connection)
        with pytest.raises(asyncpg.CheckViolationError):
            await connection.execute(
                """
                INSERT INTO consent_records (subject_user_id, consent_type, status)
                VALUES ($1, 'data_processing', 'confirmed')
                """,
                subject_id,
            )
    finally:
        await connection.close()


async def test_pending_consent_rejects_confirmation_fields() -> None:
    connection = await asyncpg.connect(asyncpg_url())
    try:
        subject_id = await create_user(connection)
        admin_id = await create_user(connection, role="senco_admin", auth_method="email_password")
        with pytest.raises(asyncpg.CheckViolationError):
            await connection.execute(
                """
                INSERT INTO consent_records (
                    subject_user_id, consent_type, status,
                    confirmed_by_admin_id, confirmed_via, confirmed_at
                )
                VALUES ($1, 'data_processing', 'pending', $2, 'written', now())
                """,
                subject_id,
                admin_id,
            )
    finally:
        await connection.close()


async def test_learner_profile_requires_existing_user() -> None:
    connection = await asyncpg.connect(asyncpg_url())
    try:
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await connection.execute(
                "INSERT INTO learner_profiles (learner_id) VALUES ($1)",
                uuid.uuid4(),
            )
    finally:
        await connection.close()
