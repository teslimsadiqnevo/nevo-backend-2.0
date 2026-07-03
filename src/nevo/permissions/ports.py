from datetime import datetime
from typing import Protocol
from uuid import UUID

from nevo.domain.permissions.vocabulary import PermissionScope
from nevo.permissions.entities import (
    AcceptedInvitation,
    AdminTeamMember,
    InvitationDraft,
    PermissionSnapshot,
)


class PermissionRepository(Protocol):
    async def snapshot(self, user_id: UUID) -> PermissionSnapshot | None: ...

    async def list_team(self, school_id: UUID) -> list[AdminTeamMember]: ...

    async def create_invitation(
        self,
        draft: InvitationDraft,
    ) -> InvitationDraft: ...

    async def accept_invitation(
        self,
        *,
        token_digest: str,
        password_hash: str,
        accepted_at: datetime,
    ) -> AcceptedInvitation | None: ...

    async def replace_scopes(
        self,
        *,
        school_id: UUID,
        target_user_id: UUID,
        scopes: frozenset[PermissionScope],
        changed_by_user_id: UUID,
        changed_at: datetime,
    ) -> AdminTeamMember | None: ...


class InvitationTokenService(Protocol):
    def issue(self) -> tuple[str, str]: ...

    def digest(self, token: str) -> str: ...


class PasswordHasher(Protocol):
    def hash_password(self, password: str) -> str: ...
