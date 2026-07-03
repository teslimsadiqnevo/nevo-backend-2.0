from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from nevo.domain.permissions.vocabulary import PermissionScope


@dataclass(frozen=True, slots=True)
class PermissionSnapshot:
    user_id: UUID
    school_id: UUID | None
    role: str
    status: str
    school_auth_method: str | None
    assigned_scopes: frozenset[PermissionScope]


@dataclass(frozen=True, slots=True)
class AdminTeamMember:
    user_id: UUID
    admin_id: UUID
    school_id: UUID
    email: str | None
    first_name: str | None
    last_name: str | None
    role: str
    status: str
    scopes: frozenset[PermissionScope]


@dataclass(frozen=True, slots=True)
class InvitationDraft:
    invitation_id: UUID
    user_id: UUID
    admin_id: UUID
    school_id: UUID
    email: str
    role: str
    scopes: frozenset[PermissionScope]
    token_digest: str
    invited_by_user_id: UUID
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class IssuedInvitation:
    invitation_id: UUID
    user_id: UUID
    email: str
    role: str
    scopes: frozenset[PermissionScope]
    invitation_token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class AcceptedInvitation:
    user_id: UUID
    school_id: UUID
    role: str
