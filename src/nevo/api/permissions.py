from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field

from nevo.api.auth import PrincipalDependency
from nevo.api.casing import CAMEL_CONFIG
from nevo.domain.accounts.vocabulary import UserRole, UserStatus
from nevo.domain.permissions.vocabulary import PermissionScope, navigation_for
from nevo.permissions.entities import (
    AdminTeamMember,
    IssuedInvitation,
    PermissionSnapshot,
)
from nevo.permissions.errors import (
    AdminSeatLimitReachedError,
    InvalidAdminRoleError,
    InvalidInvitationError,
    LastOversightAdminError,
    PermissionDeniedError,
    PermissionError,
    SelfDeactivationError,
    SelfScopeRemovalError,
    SsoManagedTeamError,
    TeamMemberAlreadyExistsError,
    TeamMemberNotFoundError,
)
from nevo.permissions.service import PermissionService

router = APIRouter(prefix="/api/v1", tags=["permissions"])


class PermissionResponse(BaseModel):
    model_config = CAMEL_CONFIG

    user_id: UUID
    school_id: UUID | None
    role: UserRole
    scopes: list[PermissionScope] = Field(max_length=50)
    navigation: list[str]

    @classmethod
    def from_snapshot(cls, snapshot: PermissionSnapshot) -> "PermissionResponse":
        scopes = sorted(snapshot.assigned_scopes, key=lambda scope: scope.value)
        return cls(
            user_id=snapshot.user_id,
            school_id=snapshot.school_id,
            role=snapshot.role,
            scopes=scopes,
            navigation=list(navigation_for(snapshot.assigned_scopes)),
        )


class TeamMemberResponse(BaseModel):
    model_config = CAMEL_CONFIG

    user_id: UUID
    admin_id: UUID
    email: str | None
    first_name: str | None
    last_name: str | None
    role: UserRole
    status: UserStatus
    scopes: list[PermissionScope] = Field(max_length=50)
    founding: bool = False
    last_active_at: datetime | None = Field(default=None, alias="lastActiveAt")

    @classmethod
    def from_member(cls, member: AdminTeamMember) -> "TeamMemberResponse":
        return cls(
            user_id=member.user_id,
            admin_id=member.admin_id,
            email=member.email,
            first_name=member.first_name,
            last_name=member.last_name,
            role=member.role,
            status=member.status,
            scopes=sorted(member.scopes, key=lambda scope: scope.value),
            founding=member.founding,
            lastActiveAt=member.last_active_at,
        )


class AdminTeamResponse(BaseModel):
    model_config = CAMEL_CONFIG

    members: list[TeamMemberResponse]
    seat_limit: int = Field(alias="seatLimit", ge=1)
    seats_used: int = Field(alias="seatsUsed", ge=0)
    seats_remaining: int = Field(alias="seatsRemaining", ge=0)


class InviteAdminRequest(BaseModel):
    email: EmailStr
    role: UserRole
    scopes: set[PermissionScope]


class AdminInvitationResponse(BaseModel):
    model_config = CAMEL_CONFIG

    invitation_id: UUID
    user_id: UUID
    email: EmailStr
    role: UserRole
    scopes: list[PermissionScope] = Field(max_length=50)
    invitation_token: str
    expires_at: datetime

    @classmethod
    def from_invitation(cls, invitation: IssuedInvitation) -> "AdminInvitationResponse":
        return cls(
            invitation_id=invitation.invitation_id,
            user_id=invitation.user_id,
            email=invitation.email,
            role=invitation.role,
            scopes=sorted(invitation.scopes, key=lambda scope: scope.value),
            invitation_token=invitation.invitation_token,
            expires_at=invitation.expires_at,
        )


class AcceptInvitationRequest(BaseModel):
    model_config = CAMEL_CONFIG

    invitation_token: str = Field(min_length=32, max_length=512)
    password: str = Field(min_length=8, max_length=1_024)


class AcceptedInvitationResponse(BaseModel):
    model_config = CAMEL_CONFIG

    user_id: UUID
    school_id: UUID
    role: UserRole


class ReplaceScopesRequest(BaseModel):
    scopes: set[PermissionScope]


def get_permission_service(request: Request) -> PermissionService:
    service = getattr(request.app.state, "permission_service", None)
    if not isinstance(service, PermissionService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_unavailable",
                "message": "Permissions are temporarily unavailable.",
            },
        )
    return service


PermissionServiceDependency = Annotated[
    PermissionService,
    Depends(get_permission_service),
]


class RequireScope:
    def __init__(self, scope: PermissionScope) -> None:
        self.scope = scope

    async def __call__(
        self,
        principal: PrincipalDependency,
        service: PermissionServiceDependency,
    ) -> PermissionSnapshot:
        try:
            return await service.require(principal, self.scope)
        except PermissionError as error:
            raise public_permission_error(error) from error


class RequireAnyScope:
    """Holds any one of several scopes.

    Some work belongs to more than one job. Asking a parent for consent is
    roster work during onboarding and learning-support work afterwards, and
    requiring the narrower of the two meant a school that had only just signed
    up could not ask anybody for anything.
    """

    def __init__(self, *scopes: PermissionScope) -> None:
        if not scopes:
            raise ValueError("at least one scope is required")
        self.scopes = scopes

    async def __call__(
        self,
        principal: PrincipalDependency,
        service: PermissionServiceDependency,
    ) -> PermissionSnapshot:
        last: PermissionError | None = None
        for scope in self.scopes:
            try:
                return await service.require(principal, scope)
            except PermissionError as error:
                last = error
        assert last is not None
        raise public_permission_error(last) from last


def scope_dependency(
    scope: PermissionScope,
) -> Callable[..., Awaitable[PermissionSnapshot]]:
    return RequireScope(scope)


OversightDependency = Annotated[
    PermissionSnapshot,
    Depends(RequireScope(PermissionScope.OVERSIGHT)),
]


@router.get("/permissions/me", response_model=PermissionResponse)
async def my_permissions(
    principal: PrincipalDependency,
    service: PermissionServiceDependency,
) -> PermissionResponse:
    try:
        snapshot = await service.permissions_for(principal)
    except PermissionError as error:
        raise public_permission_error(error) from error
    return PermissionResponse.from_snapshot(snapshot)


@router.get("/admin/team", response_model=AdminTeamResponse)
async def list_admin_team(
    principal: PrincipalDependency,
    service: PermissionServiceDependency,
) -> AdminTeamResponse:
    try:
        members = await service.list_team(principal)
        seat_limit = await service.team_seat_limit(principal)
    except PermissionError as error:
        raise public_permission_error(error) from error
    seats_used = sum(member.status in {"active", "invited"} for member in members)
    return AdminTeamResponse(
        members=[TeamMemberResponse.from_member(member) for member in members],
        seatLimit=seat_limit,
        seatsUsed=seats_used,
        seatsRemaining=max(0, seat_limit - seats_used),
    )


@router.post(
    "/admin/team/invitations",
    response_model=AdminInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_admin(
    payload: InviteAdminRequest,
    principal: PrincipalDependency,
    service: PermissionServiceDependency,
    response: Response,
) -> AdminInvitationResponse:
    try:
        invitation = await service.invite(
            principal,
            email=str(payload.email),
            role=payload.role.value,
            scopes=frozenset(payload.scopes),
        )
    except PermissionError as error:
        raise public_permission_error(error) from error
    response.headers["Cache-Control"] = "no-store"
    return AdminInvitationResponse.from_invitation(invitation)


@router.post(
    "/admin/team/invitations/accept",
    response_model=AcceptedInvitationResponse,
)
async def accept_invitation(
    payload: AcceptInvitationRequest,
    service: PermissionServiceDependency,
) -> AcceptedInvitationResponse:
    try:
        accepted = await service.accept_invitation(
            token=payload.invitation_token,
            password=payload.password,
        )
    except PermissionError as error:
        raise public_permission_error(error) from error
    return AcceptedInvitationResponse(
        user_id=accepted.user_id,
        school_id=accepted.school_id,
        role=accepted.role,
    )


@router.put(
    "/admin/team/{target_user_id}/scopes",
    response_model=TeamMemberResponse,
)
async def replace_admin_scopes(
    target_user_id: UUID,
    payload: ReplaceScopesRequest,
    principal: PrincipalDependency,
    service: PermissionServiceDependency,
) -> TeamMemberResponse:
    try:
        member = await service.replace_scopes(
            principal,
            target_user_id=target_user_id,
            scopes=frozenset(payload.scopes),
        )
    except PermissionError as error:
        raise public_permission_error(error) from error
    return TeamMemberResponse.from_member(member)


@router.post(
    "/admin/team/{target_user_id}/deactivate",
    response_model=TeamMemberResponse,
)
async def deactivate_admin_team_member(
    target_user_id: UUID,
    principal: PrincipalDependency,
    service: PermissionServiceDependency,
) -> TeamMemberResponse:
    try:
        member = await service.set_team_member_active(
            principal, target_user_id=target_user_id, active=False
        )
    except PermissionError as error:
        raise public_permission_error(error) from error
    return TeamMemberResponse.from_member(member)


@router.post(
    "/admin/team/{target_user_id}/restore",
    response_model=TeamMemberResponse,
)
async def restore_admin_team_member(
    target_user_id: UUID,
    principal: PrincipalDependency,
    service: PermissionServiceDependency,
) -> TeamMemberResponse:
    try:
        member = await service.set_team_member_active(
            principal, target_user_id=target_user_id, active=True
        )
    except PermissionError as error:
        raise public_permission_error(error) from error
    return TeamMemberResponse.from_member(member)


def public_permission_error(error: PermissionError) -> HTTPException:
    status_code = status.HTTP_400_BAD_REQUEST
    if isinstance(error, PermissionDeniedError):
        status_code = status.HTTP_403_FORBIDDEN
    elif isinstance(error, TeamMemberNotFoundError):
        status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(
        error,
        (
            TeamMemberAlreadyExistsError,
            LastOversightAdminError,
            SelfScopeRemovalError,
            SelfDeactivationError,
            SsoManagedTeamError,
            AdminSeatLimitReachedError,
        ),
    ):
        status_code = status.HTTP_409_CONFLICT
    elif isinstance(error, (InvalidInvitationError, InvalidAdminRoleError)):
        status_code = status.HTTP_400_BAD_REQUEST
    return HTTPException(
        status_code=status_code,
        detail={
            "code": error.code,
            "message": error.public_message,
        },
    )
