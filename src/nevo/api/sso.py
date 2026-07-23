from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from nevo.api.permissions import RequireScope
from nevo.domain.accounts.vocabulary import (
    RosterSyncStatus,
    SsoFirstUseDestination,
    SsoProvider,
)
from nevo.domain.permissions.vocabulary import PermissionScope
from nevo.permissions.entities import PermissionSnapshot
from nevo.sso.entities import RosterSyncResult, SsoLoginResult, SsoStart
from nevo.sso.service import SsoService

router = APIRouter(prefix="/api/v1", tags=["sso"])


class SsoStartResponse(BaseModel):
    authorization_url: str
    school_entry_url: str

    @classmethod
    def from_start(cls, start: SsoStart) -> "SsoStartResponse":
        return cls(
            authorization_url=start.authorization_url,
            school_entry_url=start.school_entry_url,
        )


class SsoCallbackResponse(BaseModel):
    access_token: str
    token_type: str
    expires_at: str
    user_id: str
    role: str
    replaced_session: bool
    destination: SsoFirstUseDestination

    @classmethod
    def from_result(cls, result: SsoLoginResult) -> "SsoCallbackResponse":
        return cls(
            access_token=result.session.access_token,
            token_type=result.session.token_type,
            expires_at=result.session.expires_at.isoformat(),
            user_id=str(result.session.user_id),
            role=result.session.role,
            replaced_session=result.session.replaced_session,
            destination=result.destination,
        )


class RosterSyncResponse(BaseModel):
    status: RosterSyncStatus
    imported_students: int
    imported_teachers: int
    missing_teacher_class_mappings: int
    issue_ids: list[str]

    @classmethod
    def from_result(cls, result: RosterSyncResult) -> "RosterSyncResponse":
        return cls(
            status=result.status,
            imported_students=result.imported_students,
            imported_teachers=result.imported_teachers,
            missing_teacher_class_mappings=result.missing_teacher_class_mappings,
            issue_ids=[str(item) for item in result.issue_ids],
        )


def get_sso_service(request: Request) -> SsoService:
    service = getattr(request.app.state, "sso_service", None)
    if not isinstance(service, SsoService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_unavailable",
                "message": "SSO is temporarily unavailable.",
            },
        )
    return service


SsoDependency = Annotated[SsoService, Depends(get_sso_service)]
ItSsoDependency = Annotated[
    PermissionSnapshot,
    Depends(RequireScope(PermissionScope.IT_SSO)),
]


@router.get(
    "/schools/{school_slug}/sso/{provider}/start",
    response_model=SsoStartResponse,
)
async def start_sso(
    school_slug: str,
    provider: SsoProvider,
    service: SsoDependency,
) -> SsoStartResponse:
    try:
        return SsoStartResponse.from_start(
            await service.start(school_slug=school_slug, provider=provider)
        )
    except LookupError as error:
        raise _public_sso_error(error) from error


@router.get(
    "/auth/sso/{provider}/callback",
    response_model=SsoCallbackResponse,
)
async def sso_callback(
    provider: SsoProvider,
    service: SsoDependency,
    code: str = Query(min_length=1),
    state: str = Query(min_length=3),
) -> SsoCallbackResponse:
    try:
        school_slug, provider_from_state = state.split(":", maxsplit=1)
        if provider_from_state != provider.value:
            raise LookupError("SSO state does not match provider")
        result = await service.callback(
            school_slug=school_slug,
            provider=provider,
            code=code,
        )
    except (LookupError, ValueError) as error:
        raise _public_sso_error(error) from error
    return SsoCallbackResponse.from_result(result)


@router.post(
    "/schools/{school_slug}/sso/{provider}/roster-sync",
    response_model=RosterSyncResponse,
)
async def sync_roster(
    school_slug: str,
    provider: SsoProvider,
    actor: ItSsoDependency,
    service: SsoDependency,
) -> RosterSyncResponse:
    del actor
    try:
        return RosterSyncResponse.from_result(
            await service.sync_roster(school_slug=school_slug, provider=provider)
        )
    except LookupError as error:
        raise _public_sso_error(error) from error


def _public_sso_error(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "code": "sso_unavailable",
            "message": str(error),
        },
    )
