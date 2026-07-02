import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from nevo.auth.entities import SessionDraft
from nevo.auth.repositories import SqlAlchemySessionRepository
from nevo.db.session import create_engine, create_session_factory

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


async def create_school_and_student(
    connection: asyncpg.Connection,
    *,
    login_identifier: str,
) -> tuple[uuid.UUID, uuid.UUID]:
    token = uuid.uuid4().hex[:12]
    school_id = await connection.fetchval(
        """
        INSERT INTO schools (name, school_code, school_url_slug, auth_method)
        VALUES ($1, $2, $3, 'pin')
        RETURNING id
        """,
        "Auth Test School",
        f"auth-{token}",
        f"auth-{token}",
    )
    student_id = await connection.fetchval(
        """
        INSERT INTO users (
            school_id,
            role,
            auth_method,
            login_identifier,
            pin_hash
        )
        VALUES ($1, 'student', 'pin', $2, 'test-hash')
        RETURNING id
        """,
        school_id,
        login_identifier,
    )
    assert isinstance(school_id, uuid.UUID)
    assert isinstance(student_id, uuid.UUID)
    return school_id, student_id


def session_draft(
    *,
    user_id: uuid.UUID,
    role: str,
    token_character: str,
) -> SessionDraft:
    now = datetime.now(UTC)
    return SessionDraft(
        id=uuid.uuid4(),
        user_id=user_id,
        role=role,
        token_digest=token_character * 64,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=2),
    )


async def test_login_identifier_is_unique_within_school() -> None:
    connection = await asyncpg.connect(asyncpg_url())
    try:
        school_id, _ = await create_school_and_student(
            connection,
            login_identifier="UZ59R",
        )
        with pytest.raises(asyncpg.UniqueViolationError):
            await connection.execute(
                """
                INSERT INTO users (
                    school_id,
                    role,
                    auth_method,
                    login_identifier,
                    pin_hash
                )
                VALUES ($1, 'student', 'pin', 'UZ59R', 'another-hash')
                """,
                school_id,
            )
    finally:
        await connection.close()


async def test_concurrent_student_logins_leave_exactly_one_active_session() -> None:
    assert TEST_DATABASE_URL is not None
    connection = await asyncpg.connect(asyncpg_url())
    try:
        _, student_id = await create_school_and_student(
            connection,
            login_identifier=f"student-{uuid.uuid4().hex[:8]}",
        )
    finally:
        await connection.close()

    engine = create_engine(TEST_DATABASE_URL)
    repository = SqlAlchemySessionRepository(create_session_factory(engine))
    first = session_draft(user_id=student_id, role="student", token_character="a")
    second = session_draft(user_id=student_id, role="student", token_character="b")
    try:
        await asyncio.gather(
            repository.create(first, replace_active=True),
            repository.create(second, replace_active=True),
        )
    finally:
        await engine.dispose()

    connection = await asyncpg.connect(asyncpg_url())
    try:
        active_count = await connection.fetchval(
            """
            SELECT count(*)
            FROM auth_sessions
            WHERE user_id = $1 AND revoked_at IS NULL
            """,
            student_id,
        )
        replaced_count = await connection.fetchval(
            """
            SELECT count(*)
            FROM auth_sessions
            WHERE user_id = $1
              AND revocation_reason = 'concurrent_login'
              AND replaced_by_session_id IS NOT NULL
            """,
            student_id,
        )
    finally:
        await connection.close()

    assert active_count == 1
    assert replaced_count == 1


async def test_teacher_sessions_can_remain_active_together() -> None:
    assert TEST_DATABASE_URL is not None
    connection = await asyncpg.connect(asyncpg_url())
    try:
        teacher_id = await connection.fetchval(
            """
            INSERT INTO users (role, auth_method, email, password_hash)
            VALUES ('teacher', 'email_password', $1, 'test-hash')
            RETURNING id
            """,
            f"teacher-{uuid.uuid4().hex[:8]}@example.com",
        )
    finally:
        await connection.close()
    assert isinstance(teacher_id, uuid.UUID)

    engine = create_engine(TEST_DATABASE_URL)
    repository = SqlAlchemySessionRepository(create_session_factory(engine))
    try:
        await repository.create(
            session_draft(
                user_id=teacher_id,
                role="teacher",
                token_character="c",
            ),
            replace_active=False,
        )
        await repository.create(
            session_draft(
                user_id=teacher_id,
                role="teacher",
                token_character="d",
            ),
            replace_active=False,
        )
    finally:
        await engine.dispose()

    connection = await asyncpg.connect(asyncpg_url())
    try:
        active_count = await connection.fetchval(
            """
            SELECT count(*)
            FROM auth_sessions
            WHERE user_id = $1 AND revoked_at IS NULL
            """,
            teacher_id,
        )
    finally:
        await connection.close()

    assert active_count == 2
