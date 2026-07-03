from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AuthUser:
    id: UUID
    school_id: UUID | None
    role: str
    auth_method: str
    status: str
    email: str | None = None
    password_hash: str | None = None
    pin_hash: str | None = None
    login_identifier: str | None = None
    school_auth_method: str | None = None
    deactivated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SessionDraft:
    id: UUID
    user_id: UUID
    role: str
    token_digest: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class SessionRecord:
    id: UUID
    user_id: UUID
    role: str
    token_digest: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    revocation_reason: str | None = None
    replaced_by_session_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class AuthPrincipal:
    user_id: UUID
    role: str
    session_id: UUID


@dataclass(frozen=True, slots=True)
class IssuedSession:
    access_token: str
    token_type: str
    expires_at: datetime
    user_id: UUID
    role: str
    replaced_session: bool
