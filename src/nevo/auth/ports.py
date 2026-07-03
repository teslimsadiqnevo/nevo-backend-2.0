from datetime import datetime
from typing import Protocol
from uuid import UUID

from nevo.auth.entities import AuthUser, SessionDraft, SessionRecord


class UserRepository(Protocol):
    async def find_by_email(self, email: str) -> AuthUser | None: ...

    async def find_pin_user(
        self,
        school_code: str,
        login_identifier: str,
    ) -> AuthUser | None: ...

    async def find_by_id(self, user_id: UUID) -> AuthUser | None: ...


class SessionRepository(Protocol):
    async def create(
        self,
        draft: SessionDraft,
        *,
        replace_active: bool,
    ) -> SessionRecord | None: ...

    async def find_by_digest(self, token_digest: str) -> SessionRecord | None: ...

    async def touch(
        self,
        session_id: UUID,
        *,
        last_seen_at: datetime,
        expires_at: datetime,
    ) -> None: ...

    async def revoke(
        self,
        session_id: UUID,
        *,
        reason: str,
        revoked_at: datetime,
    ) -> None: ...


class LoginRateLimiter(Protocol):
    async def check(self, identity_digest: str, ip_digest: str) -> None: ...

    async def record(
        self,
        identity_digest: str,
        ip_digest: str,
        *,
        succeeded: bool,
        occurred_at: datetime,
    ) -> None: ...


class AuthAuditLog(Protocol):
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
    ) -> None: ...


class CredentialHasher(Protocol):
    def hash_password(self, password: str) -> str: ...

    def verify_password(self, password_hash: str | None, password: str) -> bool: ...

    def hash_pin(self, pin: str) -> str: ...

    def verify_pin(self, pin_hash: str | None, pin: str) -> bool: ...


class TokenService(Protocol):
    def issue(self) -> tuple[str, str]: ...

    def digest(self, token: str) -> str: ...

    def protect_identifier(self, value: str) -> str: ...
