import os
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from nevo.db.session import create_engine, create_session_factory
from nevo.domain.permissions.vocabulary import PermissionScope
from nevo.permissions.entities import InvitationDraft
from nevo.permissions.errors import LastOversightAdminError
from nevo.permissions.repositories import SqlAlchemyPermissionRepository

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
        VALUES ('Permission Test School', $1, $2)
        RETURNING id
        """,
        f"perm-{token}",
        f"perm-{token}",
    )
    assert isinstance(school_id, uuid.UUID)
    return school_id


async def create_admin(
    connection: asyncpg.Connection,
    *,
    school_id: uuid.UUID,
    email: str,
    role: str = "other_admin",
    scopes: tuple[str, ...] = (),
) -> tuple[uuid.UUID, uuid.UUID]:
    user_id = await connection.fetchval(
        """
        INSERT INTO users (
            school_id,
            role,
            auth_method,
            email,
            password_hash
        )
        VALUES ($1, $2, 'email_password', $3, 'test-hash')
        RETURNING id
        """,
        school_id,
        role,
        email,
    )
    admin_id = await connection.fetchval(
        """
        INSERT INTO admins (user_id, school_id)
        VALUES ($1, $2)
        RETURNING id
        """,
        user_id,
        school_id,
    )
    for scope in scopes:
        await connection.execute(
            """
            INSERT INTO admin_scope_assignments (admin_id, scope)
            VALUES ($1, $2)
            """,
            admin_id,
            scope,
        )
    assert isinstance(user_id, uuid.UUID)
    assert isinstance(admin_id, uuid.UUID)
    return user_id, admin_id


async def repository() -> tuple[SqlAlchemyPermissionRepository, object]:
    assert TEST_DATABASE_URL is not None
    engine = create_engine(TEST_DATABASE_URL)
    return SqlAlchemyPermissionRepository(create_session_factory(engine)), engine


async def test_snapshot_returns_only_active_explicit_scopes() -> None:
    connection = await asyncpg.connect(asyncpg_url())
    try:
        school_id = await create_school(connection)
        user_id, admin_id = await create_admin(
            connection,
            school_id=school_id,
            email=f"admin-{uuid.uuid4().hex[:8]}@example.com",
            scopes=("oversight", "billing"),
        )
        await connection.execute(
            """
            UPDATE admin_scope_assignments
            SET revoked_at = now()
            WHERE admin_id = $1 AND scope = 'billing'
            """,
            admin_id,
        )
    finally:
        await connection.close()

    permission_repository, engine = await repository()
    try:
        result = await permission_repository.snapshot(user_id)
    finally:
        await engine.dispose()

    assert result is not None
    assert result.school_id == school_id
    assert result.assigned_scopes == {PermissionScope.OVERSIGHT}


async def test_invitation_acceptance_activates_user_and_hash_only() -> None:
    connection = await asyncpg.connect(asyncpg_url())
    try:
        school_id = await create_school(connection)
        actor_id, _ = await create_admin(
            connection,
            school_id=school_id,
            email=f"owner-{uuid.uuid4().hex[:8]}@example.com",
            scopes=("oversight",),
        )
    finally:
        await connection.close()

    now = datetime.now(UTC)
    draft = InvitationDraft(
        invitation_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        admin_id=uuid.uuid4(),
        school_id=school_id,
        email=f"invite-{uuid.uuid4().hex[:8]}@example.com",
        role="teacher",
        scopes=frozenset({PermissionScope.CURRICULUM}),
        token_digest="a" * 64,
        invited_by_user_id=actor_id,
        created_at=now,
        expires_at=now + timedelta(days=7),
    )
    permission_repository, engine = await repository()
    try:
        await permission_repository.create_invitation(draft)
        accepted = await permission_repository.accept_invitation(
            token_digest=draft.token_digest,
            password_hash="argon2-password-hash",
            accepted_at=now + timedelta(minutes=1),
        )
    finally:
        await engine.dispose()

    connection = await asyncpg.connect(asyncpg_url())
    try:
        user = await connection.fetchrow(
            "SELECT status, password_hash FROM users WHERE id = $1",
            draft.user_id,
        )
        invitation = await connection.fetchrow(
            """
            SELECT token_digest, accepted_at
            FROM admin_invitations
            WHERE id = $1
            """,
            draft.invitation_id,
        )
    finally:
        await connection.close()

    assert accepted is not None
    assert user["status"] == "active"
    assert user["password_hash"] == "argon2-password-hash"
    assert invitation["token_digest"] == "a" * 64
    assert invitation["accepted_at"] is not None


async def test_scope_replacement_preserves_revoked_history() -> None:
    connection = await asyncpg.connect(asyncpg_url())
    try:
        school_id = await create_school(connection)
        actor_id, _ = await create_admin(
            connection,
            school_id=school_id,
            email=f"owner-{uuid.uuid4().hex[:8]}@example.com",
            scopes=("oversight",),
        )
        target_id, target_admin_id = await create_admin(
            connection,
            school_id=school_id,
            email=f"target-{uuid.uuid4().hex[:8]}@example.com",
            scopes=("billing", "roster"),
        )
    finally:
        await connection.close()

    permission_repository, engine = await repository()
    try:
        updated = await permission_repository.replace_scopes(
            school_id=school_id,
            target_user_id=target_id,
            scopes=frozenset(
                {
                    PermissionScope.ROSTER,
                    PermissionScope.CURRICULUM,
                }
            ),
            changed_by_user_id=actor_id,
            changed_at=datetime.now(UTC),
        )
    finally:
        await engine.dispose()

    connection = await asyncpg.connect(asyncpg_url())
    try:
        rows = await connection.fetch(
            """
            SELECT scope::text AS scope, revoked_at
            FROM admin_scope_assignments
            WHERE admin_id = $1
            ORDER BY scope::text, granted_at
            """,
            target_admin_id,
        )
    finally:
        await connection.close()

    assert updated is not None
    assert updated.scopes == {
        PermissionScope.ROSTER,
        PermissionScope.CURRICULUM,
    }
    history = {(row["scope"], row["revoked_at"] is None) for row in rows}
    assert history == {
        ("billing", False),
        ("curriculum", True),
        ("roster", True),
    }


async def test_last_active_oversight_scope_cannot_be_removed() -> None:
    connection = await asyncpg.connect(asyncpg_url())
    try:
        school_id = await create_school(connection)
        actor_id, _ = await create_admin(
            connection,
            school_id=school_id,
            email=f"owner-{uuid.uuid4().hex[:8]}@example.com",
            scopes=("oversight",),
        )
    finally:
        await connection.close()

    permission_repository, engine = await repository()
    try:
        with pytest.raises(LastOversightAdminError):
            await permission_repository.replace_scopes(
                school_id=school_id,
                target_user_id=actor_id,
                scopes=frozenset({PermissionScope.BILLING}),
                changed_by_user_id=actor_id,
                changed_at=datetime.now(UTC),
            )
    finally:
        await engine.dispose()
