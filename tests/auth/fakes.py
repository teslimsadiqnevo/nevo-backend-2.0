from dataclasses import replace
from datetime import datetime
from uuid import UUID

from nevo.auth.entities import AuthUser, SessionDraft, SessionRecord
from nevo.auth.errors import RateLimitExceededError


class MemoryUserRepository:
    def __init__(self, users: list[AuthUser]) -> None:
        self.users = users

    async def find_by_email(self, email: str) -> AuthUser | None:
        return next(
            (
                user
                for user in self.users
                if user.email is not None and user.email.casefold() == email.casefold()
            ),
            None,
        )

    async def find_pin_user(
        self,
        school_code: str,
        login_identifier: str,
    ) -> AuthUser | None:
        del school_code
        return next(
            (
                user
                for user in self.users
                if user.login_identifier is not None
                and user.login_identifier.casefold() == login_identifier.casefold()
            ),
            None,
        )

    async def find_by_id(self, user_id: UUID) -> AuthUser | None:
        return next((user for user in self.users if user.id == user_id), None)


class MemorySessionRepository:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionRecord] = {}

    async def create(
        self,
        draft: SessionDraft,
        *,
        replace_active: bool,
    ) -> SessionRecord | None:
        replaced_session: SessionRecord | None = None
        if replace_active:
            for digest, session in list(self.sessions.items()):
                if session.user_id == draft.user_id and session.revoked_at is None:
                    replaced_session = session
                    self.sessions[digest] = replace(
                        session,
                        revoked_at=draft.created_at,
                        revocation_reason="concurrent_login",
                        replaced_by_session_id=draft.id,
                    )

        self.sessions[draft.token_digest] = SessionRecord(
            id=draft.id,
            user_id=draft.user_id,
            role=draft.role,
            token_digest=draft.token_digest,
            created_at=draft.created_at,
            last_seen_at=draft.last_seen_at,
            expires_at=draft.expires_at,
        )
        return replaced_session

    async def find_by_digest(self, token_digest: str) -> SessionRecord | None:
        return self.sessions.get(token_digest)

    async def touch(
        self,
        session_id: UUID,
        *,
        last_seen_at: datetime,
        expires_at: datetime,
    ) -> None:
        for digest, session in self.sessions.items():
            if session.id == session_id:
                self.sessions[digest] = replace(
                    session,
                    last_seen_at=last_seen_at,
                    expires_at=expires_at,
                )
                return

    async def revoke(
        self,
        session_id: UUID,
        *,
        reason: str,
        revoked_at: datetime,
    ) -> None:
        for digest, session in self.sessions.items():
            if session.id == session_id and session.revoked_at is None:
                self.sessions[digest] = replace(
                    session,
                    revoked_at=revoked_at,
                    revocation_reason=reason,
                )
                return


class MemoryRateLimiter:
    def __init__(self) -> None:
        self.blocked = False
        self.attempts: list[tuple[str, str, bool, datetime]] = []

    async def check(self, identity_digest: str, ip_digest: str) -> None:
        del identity_digest, ip_digest
        if self.blocked:
            raise RateLimitExceededError

    async def record(
        self,
        identity_digest: str,
        ip_digest: str,
        *,
        succeeded: bool,
        occurred_at: datetime,
    ) -> None:
        self.attempts.append(
            (identity_digest, ip_digest, succeeded, occurred_at)
        )


class MemoryAuditLog:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

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
        self.events.append(
            {
                "event_type": event_type,
                "occurred_at": occurred_at,
                "user_id": user_id,
                "session_id": session_id,
                "identity_digest": identity_digest,
                "ip_digest": ip_digest,
                "details": details,
            }
        )


class FakeCredentialHasher:
    @staticmethod
    def hash_password(password: str) -> str:
        return f"password:{password}"

    @staticmethod
    def verify_password(password_hash: str | None, password: str) -> bool:
        return password_hash == f"password:{password}"

    @staticmethod
    def hash_pin(pin: str) -> str:
        return f"pin:{pin}"

    @staticmethod
    def verify_pin(pin_hash: str | None, pin: str) -> bool:
        return pin_hash == f"pin:{pin}"


class DeterministicTokenService:
    def __init__(self) -> None:
        self.counter = 0

    def issue(self) -> tuple[str, str]:
        self.counter += 1
        token = f"token-{self.counter}"
        return token, self.digest(token)

    @staticmethod
    def digest(token: str) -> str:
        return f"digest:{token}"

    @staticmethod
    def protect_identifier(value: str) -> str:
        return f"protected:{value.casefold().strip()}"
