from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from nevo.auth.entities import AuthPrincipal
from nevo.domain.permissions.vocabulary import (
    PermissionScope,
    effective_scopes,
    navigation_for,
)
from nevo.permissions.entities import (
    AcceptedInvitation,
    AdminTeamMember,
    InvitationDraft,
    IssuedInvitation,
    PermissionSnapshot,
)
from nevo.permissions.errors import (
    InvalidAdminRoleError,
    InvalidInvitationError,
    PermissionDeniedError,
    SelfScopeRemovalError,
    SsoManagedTeamError,
    TeamMemberNotFoundError,
)
from nevo.permissions.ports import (
    InvitationTokenService,
    PasswordHasher,
    PermissionRepository,
)

ACTIVE_STATUS = "active"
ADMIN_ROLES = {"teacher", "senco_admin", "other_admin"}


class PermissionService:
    def __init__(
        self,
        *,
        repository: PermissionRepository,
        invitation_tokens: InvitationTokenService,
        password_hasher: PasswordHasher,
        invitation_ttl: timedelta = timedelta(days=7),
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._invitation_tokens = invitation_tokens
        self._password_hasher = password_hasher
        self._invitation_ttl = invitation_ttl
        self._now = now or (lambda: datetime.now(UTC))

    async def permissions_for(
        self,
        principal: AuthPrincipal,
    ) -> PermissionSnapshot:
        snapshot = await self._repository.snapshot(principal.user_id)
        if snapshot is None or snapshot.status != ACTIVE_STATUS:
            raise PermissionDeniedError
        return replace(
            snapshot,
            assigned_scopes=effective_scopes(
                snapshot.role,
                snapshot.assigned_scopes,
            ),
        )

    async def require(
        self,
        principal: AuthPrincipal,
        scope: PermissionScope,
    ) -> PermissionSnapshot:
        snapshot = await self.permissions_for(principal)
        if scope not in snapshot.assigned_scopes:
            raise PermissionDeniedError
        return snapshot

    async def navigation_for(
        self,
        principal: AuthPrincipal,
    ) -> tuple[str, ...]:
        snapshot = await self.permissions_for(principal)
        return navigation_for(snapshot.assigned_scopes)

    async def list_team(
        self,
        principal: AuthPrincipal,
    ) -> list[AdminTeamMember]:
        actor = await self.require(principal, PermissionScope.OVERSIGHT)
        if actor.school_id is None:
            raise PermissionDeniedError
        members = await self._repository.list_team(actor.school_id)
        return [self._with_effective_scopes(member) for member in members]

    async def invite(
        self,
        principal: AuthPrincipal,
        *,
        email: str,
        role: str,
        scopes: frozenset[PermissionScope],
    ) -> IssuedInvitation:
        actor = await self.require(principal, PermissionScope.OVERSIGHT)
        if actor.school_id is None:
            raise PermissionDeniedError
        if actor.school_auth_method == "sso":
            raise SsoManagedTeamError
        if role not in ADMIN_ROLES:
            raise InvalidAdminRoleError
        if not scopes and role == "other_admin":
            raise PermissionDeniedError

        normalized_email = email.casefold().strip()
        token, token_digest = self._invitation_tokens.issue()
        now = self._now()
        draft = InvitationDraft(
            invitation_id=uuid4(),
            user_id=uuid4(),
            admin_id=uuid4(),
            school_id=actor.school_id,
            email=normalized_email,
            role=role,
            scopes=scopes,
            token_digest=token_digest,
            invited_by_user_id=actor.user_id,
            created_at=now,
            expires_at=now + self._invitation_ttl,
        )
        stored = await self._repository.create_invitation(draft)
        return IssuedInvitation(
            invitation_id=stored.invitation_id,
            user_id=stored.user_id,
            email=stored.email,
            role=stored.role,
            scopes=effective_scopes(stored.role, stored.scopes),
            invitation_token=token,
            expires_at=stored.expires_at,
        )

    async def accept_invitation(
        self,
        *,
        token: str,
        password: str,
    ) -> AcceptedInvitation:
        accepted = await self._repository.accept_invitation(
            token_digest=self._invitation_tokens.digest(token),
            password_hash=self._password_hasher.hash_password(password),
            accepted_at=self._now(),
        )
        if accepted is None:
            raise InvalidInvitationError
        return accepted

    async def replace_scopes(
        self,
        principal: AuthPrincipal,
        *,
        target_user_id: UUID,
        scopes: frozenset[PermissionScope],
    ) -> AdminTeamMember:
        actor = await self.require(principal, PermissionScope.OVERSIGHT)
        if actor.school_id is None:
            raise PermissionDeniedError
        if (
            target_user_id == actor.user_id
            and PermissionScope.OVERSIGHT not in scopes
        ):
            raise SelfScopeRemovalError
        member = await self._repository.replace_scopes(
            school_id=actor.school_id,
            target_user_id=target_user_id,
            scopes=scopes,
            changed_by_user_id=actor.user_id,
            changed_at=self._now(),
        )
        if member is None:
            raise TeamMemberNotFoundError
        return self._with_effective_scopes(member)

    @staticmethod
    def _with_effective_scopes(member: AdminTeamMember) -> AdminTeamMember:
        return replace(
            member,
            scopes=effective_scopes(member.role, member.scopes),
        )
