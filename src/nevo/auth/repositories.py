from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.base import Executable

from nevo.auth.entities import AuthUser, SessionDraft, SessionRecord
from nevo.auth.errors import RateLimitExceededError
from nevo.db.models.account import School, User
from nevo.db.models.auth import AuthAuditEvent, AuthLoginAttempt, AuthSession
from nevo.domain.accounts.vocabulary import UserRole


class SqlAlchemyUserRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def find_by_email(self, email: str) -> AuthUser | None:
        statement = (
            select(User, School.auth_method)
            .outerjoin(School, School.id == User.school_id)
            .where(func.lower(User.email) == email)
            .limit(1)
        )
        return await self._find(statement)

    async def find_pin_user(
        self,
        school_code: str,
        login_identifier: str,
    ) -> AuthUser | None:
        statement = (
            select(User, School.auth_method)
            .join(School, School.id == User.school_id)
            .where(
                func.lower(School.school_code) == school_code,
                func.lower(User.login_identifier) == login_identifier,
            )
            .limit(1)
        )
        return await self._find(statement)

    async def find_by_id(self, user_id: UUID) -> AuthUser | None:
        statement = (
            select(User, School.auth_method)
            .outerjoin(School, School.id == User.school_id)
            .where(User.id == user_id)
            .limit(1)
        )
        return await self._find(statement)

    async def _find(self, statement: Executable) -> AuthUser | None:
        async with self._sessions() as session:
            result = await session.execute(statement)
            row = result.one_or_none()
        if row is None:
            return None
        user, school_auth_method = row
        return AuthUser(
            id=user.id,
            school_id=user.school_id,
            role=user.role.value,
            auth_method=user.auth_method.value,
            status=user.status.value,
            email=user.email,
            password_hash=user.password_hash,
            pin_hash=user.pin_hash,
            login_identifier=user.login_identifier,
            school_auth_method=school_auth_method.value
            if school_auth_method is not None
            else None,
            deactivated_at=user.deactivated_at,
        )


class SqlAlchemySessionRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(
        self,
        draft: SessionDraft,
        *,
        replace_active: bool,
    ) -> SessionRecord | None:
        replaced: SessionRecord | None = None
        active_ids: list[UUID] = []
        async with self._sessions.begin() as session:
            if replace_active:
                await session.execute(
                    text("SELECT id FROM users WHERE id = :user_id FOR UPDATE"),
                    {"user_id": draft.user_id},
                )
                active = await session.scalars(
                    select(AuthSession)
                    .where(
                        AuthSession.user_id == draft.user_id,
                        AuthSession.revoked_at.is_(None),
                    )
                    .order_by(AuthSession.created_at.desc())
                    .with_for_update()
                )
                active_sessions = list(active)
                if active_sessions:
                    replaced = to_session_record(active_sessions[0])
                    active_ids = [old_session.id for old_session in active_sessions]
                    await session.execute(
                        update(AuthSession)
                        .where(AuthSession.id.in_(active_ids))
                        .values(
                            revoked_at=draft.created_at,
                            revocation_reason="concurrent_login",
                        )
                    )

            session.add(
                AuthSession(
                    id=draft.id,
                    user_id=draft.user_id,
                    role=UserRole(draft.role),
                    token_digest=draft.token_digest,
                    created_at=draft.created_at,
                    last_seen_at=draft.last_seen_at,
                    expires_at=draft.expires_at,
                )
            )
            await session.flush()
            if replace_active and replaced is not None:
                await session.execute(
                    update(AuthSession)
                    .where(
                        AuthSession.id.in_(active_ids),
                    )
                    .values(replaced_by_session_id=draft.id)
                )
        return replaced

    async def find_by_digest(self, token_digest: str) -> SessionRecord | None:
        async with self._sessions() as session:
            result = await session.scalar(
                select(AuthSession).where(AuthSession.token_digest == token_digest)
            )
        return to_session_record(result) if result else None

    async def touch(
        self,
        session_id: UUID,
        *,
        last_seen_at: datetime,
        expires_at: datetime,
    ) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(AuthSession)
                .where(
                    AuthSession.id == session_id,
                    AuthSession.revoked_at.is_(None),
                )
                .values(last_seen_at=last_seen_at, expires_at=expires_at)
            )

    async def revoke(
        self,
        session_id: UUID,
        *,
        reason: str,
        revoked_at: datetime,
    ) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(AuthSession)
                .where(
                    AuthSession.id == session_id,
                    AuthSession.revoked_at.is_(None),
                )
                .values(revoked_at=revoked_at, revocation_reason=reason)
            )


class SqlAlchemyLoginRateLimiter:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        max_failures: int = 5,
        window: timedelta = timedelta(minutes=15),
    ) -> None:
        self._sessions = sessions
        self._max_failures = max_failures
        self._window = window

    async def check(self, identity_digest: str, ip_digest: str) -> None:
        cutoff = datetime.now(UTC) - self._window
        statement = select(func.count()).select_from(AuthLoginAttempt).where(
            AuthLoginAttempt.succeeded.is_(False),
            AuthLoginAttempt.occurred_at >= cutoff,
            or_(
                AuthLoginAttempt.identity_digest == identity_digest,
                AuthLoginAttempt.ip_digest == ip_digest,
            ),
        )
        async with self._sessions() as session:
            failures = await session.scalar(statement)
        if failures is not None and failures >= self._max_failures:
            raise RateLimitExceededError

    async def record(
        self,
        identity_digest: str,
        ip_digest: str,
        *,
        succeeded: bool,
        occurred_at: datetime,
    ) -> None:
        async with self._sessions.begin() as session:
            session.add(
                AuthLoginAttempt(
                    identity_digest=identity_digest,
                    ip_digest=ip_digest,
                    succeeded=succeeded,
                    occurred_at=occurred_at,
                )
            )


class SqlAlchemyAuthAuditLog:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def record(
        self,
        event_type: str,
        *,
        occurred_at: datetime,
        user_id: UUID | None,
        session_id: UUID | None,
        identity_digest: str | None,
        ip_digest: str | None,
        details: dict[str, str] | None = None,
    ) -> None:
        async with self._sessions.begin() as session:
            session.add(
                AuthAuditEvent(
                    event_type=event_type,
                    occurred_at=occurred_at,
                    user_id=user_id,
                    session_id=session_id,
                    identity_digest=identity_digest,
                    ip_digest=ip_digest,
                    details=details,
                )
            )


def to_session_record(session: AuthSession) -> SessionRecord:
    return SessionRecord(
        id=session.id,
        user_id=session.user_id,
        role=session.role.value,
        token_digest=session.token_digest,
        created_at=session.created_at,
        last_seen_at=session.last_seen_at,
        expires_at=session.expires_at,
        revoked_at=session.revoked_at,
        revocation_reason=session.revocation_reason,
        replaced_by_session_id=session.replaced_by_session_id,
    )
