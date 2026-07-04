import os
import uuid
from datetime import UTC, datetime

import asyncpg
import pytest

from nevo.consent.entities import ConsentActor
from nevo.consent.repositories import SqlAlchemyConsentRepository
from nevo.consent.service import ConsentService
from nevo.db.session import create_engine, create_session_factory
from nevo.domain.accounts.vocabulary import ConsentType
from nevo.domain.consent.vocabulary import ParentContactMethod
from tests.consent.fakes import FixedConsentTokenService

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
        VALUES ('Consent Test School', $1, $2)
        RETURNING id
        """,
        f"consent-{token}",
        f"consent-{token}",
    )
    assert isinstance(school_id, uuid.UUID)
    return school_id


async def create_user(
    connection: asyncpg.Connection,
    *,
    school_id: uuid.UUID,
    role: str,
    auth_method: str,
) -> uuid.UUID:
    user_id = await connection.fetchval(
        """
        INSERT INTO users (
            school_id,
            role,
            auth_method,
            status
        )
        VALUES ($1, $2, $3, 'active')
        RETURNING id
        """,
        school_id,
        role,
        auth_method,
    )
    assert isinstance(user_id, uuid.UUID)
    return user_id


async def test_roster_student_defaults_to_pending_consent() -> None:
    connection = await asyncpg.connect(asyncpg_url())
    try:
        school_id = await create_school(connection)
        student_id = await create_user(
            connection,
            school_id=school_id,
            role="student",
            auth_method="sso",
        )
        row = await connection.fetchrow(
            """
            SELECT status, consent_type
            FROM consent_records
            WHERE subject_user_id = $1
            """,
            student_id,
        )
    finally:
        await connection.close()

    assert row is not None
    assert row["status"] == "pending"
    assert row["consent_type"] == "data_processing"


async def test_parent_link_completion_creates_stub_and_confirms_consent() -> None:
    assert TEST_DATABASE_URL is not None
    connection = await asyncpg.connect(asyncpg_url())
    try:
        school_id = await create_school(connection)
        admin_id = await create_user(
            connection,
            school_id=school_id,
            role="senco_admin",
            auth_method="email_password",
        )
        student_id = await create_user(
            connection,
            school_id=school_id,
            role="student",
            auth_method="pin",
        )
    finally:
        await connection.close()

    engine = create_engine(TEST_DATABASE_URL)
    service = ConsentService(
        repository=SqlAlchemyConsentRepository(
            create_session_factory(engine),
        ),
        token_service=FixedConsentTokenService(),
        public_base_url="https://app.nevo.test",
        now=lambda: datetime(2026, 7, 4, 12, 0, tzinfo=UTC),
    )
    try:
        queued = await service.request_parent_consent(
            ConsentActor(user_id=admin_id, school_id=school_id),
            student_id=student_id,
            parent_name="Ada Parent",
            parent_contact="ada@example.com",
            contact_method=ParentContactMethod.EMAIL,
            consent_types=frozenset({ConsentType.DATA_PROCESSING}),
        )
        completion = await service.complete_parent_consent(
            token=FixedConsentTokenService.token,
        )
        repeated = await service.complete_parent_consent(
            token=FixedConsentTokenService.token,
        )
    finally:
        await engine.dispose()

    connection = await asyncpg.connect(asyncpg_url())
    try:
        link = await connection.fetchrow(
            """
            SELECT parent_id, account_created
            FROM parent_links
            WHERE id = $1
            """,
            queued.parent_link_id,
        )
        parent = await connection.fetchrow(
            """
            SELECT role, status, email
            FROM users
            WHERE id = $1
            """,
            completion.parent_id if completion else None,
        )
        consent = await connection.fetchrow(
            """
            SELECT status, confirmation_source, confirmed_by_parent_id
            FROM consent_records
            WHERE subject_user_id = $1
              AND consent_type = 'data_processing'
            """,
            student_id,
        )
        outbox_url = await connection.fetchval(
            """
            SELECT consent_url
            FROM consent_notification_outbox
            WHERE invitation_id = $1
            """,
            queued.invitation_id,
        )
    finally:
        await connection.close()

    assert completion is not None
    assert repeated is None
    assert link is not None
    assert link["parent_id"] == completion.parent_id
    assert link["account_created"]
    assert parent is not None
    assert parent["role"] == "parent_guardian"
    assert parent["status"] == "invited"
    assert parent["email"] == "ada@example.com"
    assert consent is not None
    assert consent["status"] == "confirmed"
    assert consent["confirmation_source"] == "parent"
    assert consent["confirmed_by_parent_id"] == completion.parent_id
    assert outbox_url == ""
