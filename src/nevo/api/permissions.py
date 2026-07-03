from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field

from nevo.api.auth import PrincipalDependency
from nevo.domain.accounts.vocabulary import UserRole
from nevo.domain.permissions.vocabulary import PermissionScope, navigation_for
from nevo.permissions.entities import (
    AdminTeamMember,
    IssuedInvitation,
    PermissionSnapshot,
)
from nevo.permissions.errors import (
    InvalidAdminRoleError,
    InvalidInvitationError,
    LastOversightAdminError,
    PermissionDeniedError,
    PermissionError,
    SelfScopeRemovalError,
    SsoManagedTeamError,
    TeamMemberAlreadyExistsError,
    TeamMemberNotFoundError,
)
from nevo.permissions.service import PermissionService

router = APIRouter(prefix="/api/v1", tags=["permissions"])


class PermissionResponse(BaseModel):
    user_id: UUID
    school_id: UUID | None
    role: str
    scopes: list[PermissionScope]
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
    user_id: UUID
    admin_id: UUID
    email: str | None
    first_name: str | None
    last_name: str | None
    role: str
    status: str
    scopes: list[PermissionScope]

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
        )


class InviteAdminRequest(BaseModel):
    email: EmailStr
    role: UserRole
    scopes: set[PermissionScope]


class InvitationResponse(BaseModel):
    invitation_id: UUID
    user_id: UUID
    email: EmailStr
    role: str
    scopes: list[PermissionScope]
    invitation_token: str
    expires_at: datetime

    @classmethod
    def from_invitation(cls, invitation: IssuedInvitation) -> "InvitationResponse":
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
    invitation_token: str = Field(min_length=32, max_length=512)
    password: str = Field(min_length=8, max_length=1_024)


class AcceptedInvitationResponse(BaseModel):
    user_id: UUID
    school_id: UUID
    role: str


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


@router.get("/admin/team", response_model=list[TeamMemberResponse])
async def list_admin_team(
    principal: PrincipalDependency,
    service: PermissionServiceDependency,
) -> list[TeamMemberResponse]:
    try:
        members = await service.list_team(principal)
    except PermissionError as error:
        raise public_permission_error(error) from error
    return [TeamMemberResponse.from_member(member) for member in members]


@router.post(
    "/admin/team/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_admin(
    payload: InviteAdminRequest,
    principal: PrincipalDependency,
    service: PermissionServiceDependency,
    response: Response,
) -> InvitationResponse:
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
    return InvitationResponse.from_invitation(invitation)


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
            SsoManagedTeamError,
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
