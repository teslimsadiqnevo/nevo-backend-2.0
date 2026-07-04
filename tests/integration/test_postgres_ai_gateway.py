import os
import uuid
from decimal import Decimal

import asyncpg
import pytest

from nevo.ai_gateway.entities import AiCallAudit
from nevo.ai_gateway.errors import InvalidAiContextError
from nevo.ai_gateway.repositories import (
    SqlAlchemyAiCallRepository,
    SqlAlchemyPromptTemplateRepository,
)
from nevo.db.session import create_engine, create_session_factory
from nevo.domain.ai_gateway.vocabulary import (
    AiCallStatus,
    AiPriority,
    AiProviderName,
    AiService,
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
        VALUES ('AI Gateway School', $1, $2)
        RETURNING id
        """,
        f"ai-{token}",
        f"ai-{token}",
    )
    assert isinstance(school_id, uuid.UUID)
    return school_id


async def create_user(
    connection: asyncpg.Connection,
    *,
    school_id: uuid.UUID,
    role: str,
) -> uuid.UUID:
    user_id = await connection.fetchval(
        """
        INSERT INTO users (school_id, role, auth_method, status)
        VALUES ($1, $2, 'email_password', 'active')
        RETURNING id
        """,
        school_id,
        role,
    )
    assert isinstance(user_id, uuid.UUID)
    return user_id


async def test_seeded_template_and_call_telemetry_are_persisted() -> None:
    assert TEST_DATABASE_URL is not None
    connection = await asyncpg.connect(asyncpg_url())
    try:
        school_id = await create_school(connection)
        requester_id = await create_user(
            connection,
            school_id=school_id,
            role="teacher",
        )
        student_id = await create_user(
            connection,
            school_id=school_id,
            role="student",
        )
    finally:
        await connection.close()

    engine = create_engine(TEST_DATABASE_URL)
    sessions = create_session_factory(engine)
    prompts = SqlAlchemyPromptTemplateRepository(sessions)
    calls = SqlAlchemyAiCallRepository(sessions)
    try:
        template = await prompts.active(
            name="adaptation.default",
            service=AiService.ADAPTATION,
        )
        assert template is not None
        context = await calls.resolve_context(
            requester_user_id=requester_id,
            student_id=student_id,
        )
        call_id = await calls.record(
            AiCallAudit(
                context=context,
                template_id=template.id,
                service=AiService.ADAPTATION,
                priority=AiPriority.ADAPTATION,
                provider=AiProviderName.GEMINI,
                model="gemini-test",
                status=AiCallStatus.SUCCEEDED,
                input_tokens=20,
                output_tokens=10,
                thought_tokens=2,
                latency_ms=120,
                estimated_cost_usd=Decimal("0.0001"),
                compliance_retries=0,
                fallback_used=False,
            )
        )
    finally:
        await engine.dispose()

    connection = await asyncpg.connect(asyncpg_url())
    try:
        row = await connection.fetchrow(
            """
            SELECT school_id, student_id, input_tokens, estimated_cost_usd
            FROM ai_gateway_calls
            WHERE id = $1
            """,
            call_id,
        )
    finally:
        await connection.close()

    assert row is not None
    assert row["school_id"] == school_id
    assert row["student_id"] == student_id
    assert row["input_tokens"] == 20
    assert row["estimated_cost_usd"] == Decimal("0.00010000")


async def test_cross_school_student_context_is_rejected() -> None:
    assert TEST_DATABASE_URL is not None
    connection = await asyncpg.connect(asyncpg_url())
    try:
        school_id = await create_school(connection)
        other_school_id = await create_school(connection)
        requester_id = await create_user(
            connection,
            school_id=school_id,
            role="teacher",
        )
        student_id = await create_user(
            connection,
            school_id=other_school_id,
            role="student",
        )
    finally:
        await connection.close()

    engine = create_engine(TEST_DATABASE_URL)
    calls = SqlAlchemyAiCallRepository(create_session_factory(engine))
    try:
        with pytest.raises(InvalidAiContextError):
            await calls.resolve_context(
                requester_user_id=requester_id,
                student_id=student_id,
            )
    finally:
        await engine.dispose()
