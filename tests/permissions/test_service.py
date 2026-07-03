from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from nevo.auth.entities import AuthPrincipal
from nevo.domain.permissions.vocabulary import PermissionScope
from nevo.permissions.entities import AdminTeamMember, PermissionSnapshot
from nevo.permissions.errors import (
    InvalidAdminRoleError,
    InvalidInvitationError,
    LastOversightAdminError,
    PermissionDeniedError,
    SelfScopeRemovalError,
    SsoManagedTeamError,
    TeamMemberNotFoundError,
)
from nevo.permissions.service import PermissionService

from .fakes import (
    DeterministicInvitationTokens,
    FakePasswordHasher,
    MemoryPermissionRepository,
)

NOW = datetime(2026, 7, 3, 9, 0, tzinfo=UTC)


@dataclass
class MutableClock:
    value: datetime = NOW

    def __call__(self) -> datetime:
        return self.value


def snapshot(
    *,
    role: str = "other_admin",
    scopes: frozenset[PermissionScope] = frozenset(
        {PermissionScope.OVERSIGHT}
    ),
    status: str = "active",
    school_auth_method: str = "email_password",
) -> PermissionSnapshot:
    return PermissionSnapshot(
        user_id=uuid4(),
        school_id=uuid4(),
        role=role,
        status=status,
        school_auth_method=school_auth_method,
        assigned_scopes=scopes,
    )


def principal_for(actor: PermissionSnapshot) -> AuthPrincipal:
    return AuthPrincipal(
        user_id=actor.user_id,
        role=actor.role,
        session_id=uuid4(),
    )


def service_for(
    actor: PermissionSnapshot,
) -> tuple[PermissionService, MemoryPermissionRepository, MutableClock]:
    repository = MemoryPermissionRepository([actor])
    clock = MutableClock()
    service = PermissionService(
        repository=repository,
        invitation_tokens=DeterministicInvitationTokens(),
        password_hasher=FakePasswordHasher(),
        now=clock,
    )
    return service, repository, clock


async def test_permissions_include_role_scope_and_assigned_scopes() -> None:
    actor = snapshot(
        role="teacher",
        scopes=frozenset({PermissionScope.CURRICULUM}),
    )
    service, _, _ = service_for(actor)

    result = await service.permissions_for(principal_for(actor))

    assert result.assigned_scopes == {
        PermissionScope.TEACHER,
        PermissionScope.CURRICULUM,
    }


async def test_required_scope_is_denied_immediately_when_not_assigned() -> None:
    actor = snapshot(scopes=frozenset({PermissionScope.BILLING}))
    service, _, _ = service_for(actor)

    with pytest.raises(PermissionDeniedError):
        await service.require(
            principal_for(actor),
            PermissionScope.OVERSIGHT,
        )


async def test_inactive_account_cannot_resolve_permissions() -> None:
    actor = snapshot(status="deactivated")
    service, _, _ = service_for(actor)

    with pytest.raises(PermissionDeniedError):
        await service.permissions_for(principal_for(actor))


async def test_invite_normalizes_email_and_issues_seven_day_token() -> None:
    actor = snapshot()
    service, repository, _ = service_for(actor)

    invitation = await service.invite(
        principal_for(actor),
        email=" New.Teacher@Example.com ",
        role="teacher",
        scopes=frozenset({PermissionScope.CURRICULUM}),
    )

    assert invitation.email == "new.teacher@example.com"
    assert invitation.expires_at == NOW + timedelta(days=7)
    assert invitation.scopes == {
        PermissionScope.TEACHER,
        PermissionScope.CURRICULUM,
    }
    assert (
        repository.invitations[f"digest:{invitation.invitation_token}"].school_id
        == actor.school_id
    )


async def test_student_cannot_be_invited_to_admin_team() -> None:
    actor = snapshot()
    service, _, _ = service_for(actor)

    with pytest.raises(InvalidAdminRoleError):
        await service.invite(
            principal_for(actor),
            email="student@example.com",
            role="student",
            scopes=frozenset({PermissionScope.ROSTER}),
        )


async def test_sso_school_rejects_manual_invitation() -> None:
    actor = snapshot(school_auth_method="sso")
    service, _, _ = service_for(actor)

    with pytest.raises(SsoManagedTeamError):
        await service.invite(
            principal_for(actor),
            email="admin@example.com",
            role="other_admin",
            scopes=frozenset({PermissionScope.ROSTER}),
        )


async def test_accept_invitation_hashes_password_and_activates_member() -> None:
    actor = snapshot()
    service, repository, _ = service_for(actor)
    invitation = await service.invite(
        principal_for(actor),
        email="admin@example.com",
        role="other_admin",
        scopes=frozenset({PermissionScope.BILLING}),
    )

    accepted = await service.accept_invitation(
        token=invitation.invitation_token,
        password="valid-password",
    )

    assert accepted.user_id == invitation.user_id
    assert repository.password_hashes[invitation.user_id] == (
        "hashed:valid-password"
    )


async def test_reinviting_pending_user_replaces_token_and_scopes() -> None:
    actor = snapshot()
    service, repository, clock = service_for(actor)
    first = await service.invite(
        principal_for(actor),
        email="pending@example.com",
        role="teacher",
        scopes=frozenset({PermissionScope.CURRICULUM}),
    )
    clock.value = NOW + timedelta(days=1)

    second = await service.invite(
        principal_for(actor),
        email="pending@example.com",
        role="senco_admin",
        scopes=frozenset({PermissionScope.ROSTER}),
    )

    assert second.user_id == first.user_id
    assert second.invitation_token != first.invitation_token
    assert second.scopes == {
        PermissionScope.SENCO,
        PermissionScope.ROSTER,
    }
    assert f"digest:{first.invitation_token}" not in repository.invitations
    assert f"digest:{second.invitation_token}" in repository.invitations


async def test_expired_invitation_is_rejected() -> None:
    actor = snapshot()
    service, _, clock = service_for(actor)
    invitation = await service.invite(
        principal_for(actor),
        email="admin@example.com",
        role="other_admin",
        scopes=frozenset({PermissionScope.BILLING}),
    )
    clock.value = invitation.expires_at

    with pytest.raises(InvalidInvitationError):
        await service.accept_invitation(
            token=invitation.invitation_token,
            password="valid-password",
        )


async def test_team_list_returns_effective_scopes() -> None:
    actor = snapshot()
    service, repository, _ = service_for(actor)
    member = AdminTeamMember(
        user_id=uuid4(),
        admin_id=uuid4(),
        school_id=actor.school_id,
        email="teacher@example.com",
        first_name="Ada",
        last_name="Okafor",
        role="teacher",
        status="active",
        scopes=frozenset({PermissionScope.CURRICULUM}),
    )
    assert actor.school_id is not None
    repository.team[actor.school_id] = [member]

    result = await service.list_team(principal_for(actor))

    assert result[0].scopes == {
        PermissionScope.TEACHER,
        PermissionScope.CURRICULUM,
    }


async def test_admin_cannot_remove_own_oversight_scope() -> None:
    actor = snapshot()
    service, _, _ = service_for(actor)

    with pytest.raises(SelfScopeRemovalError):
        await service.replace_scopes(
            principal_for(actor),
            target_user_id=actor.user_id,
            scopes=frozenset({PermissionScope.BILLING}),
        )


async def test_last_oversight_error_is_preserved() -> None:
    actor = snapshot()
    service, repository, _ = service_for(actor)
    target = AdminTeamMember(
        user_id=uuid4(),
        admin_id=uuid4(),
        school_id=actor.school_id,
        email="admin@example.com",
        first_name=None,
        last_name=None,
        role="other_admin",
        status="active",
        scopes=frozenset({PermissionScope.OVERSIGHT}),
    )
    assert actor.school_id is not None
    repository.team[actor.school_id] = [target]
    repository.raise_last_oversight = True

    with pytest.raises(LastOversightAdminError):
        await service.replace_scopes(
            principal_for(actor),
            target_user_id=target.user_id,
            scopes=frozenset({PermissionScope.BILLING}),
        )


async def test_cross_school_or_unknown_member_is_not_exposed() -> None:
    actor = snapshot()
    service, _, _ = service_for(actor)

    with pytest.raises(TeamMemberNotFoundError):
        await service.replace_scopes(
            principal_for(actor),
            target_user_id=uuid4(),
            scopes=frozenset({PermissionScope.BILLING}),
        )
