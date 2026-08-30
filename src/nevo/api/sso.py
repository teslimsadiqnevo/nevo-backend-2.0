from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from nevo.api.permissions import RequireScope
from nevo.domain.accounts.vocabulary import (
    RosterSyncStatus,
    SsoConnectionStatus,
    SsoFirstUseDestination,
    SsoProvider,
)
from nevo.domain.permissions.vocabulary import PermissionScope
from nevo.permissions.entities import PermissionSnapshot
from nevo.sso.entities import (
    RosterSyncHistory,
    RosterSyncResult,
    RosterSyncRunView,
    SsoConnectionHealth,
    SsoDisconnection,
    SsoLoginResult,
    SsoReauthorisation,
    SsoStart,
)
from nevo.sso.service import (
    DEFAULT_SYNC_HISTORY_WINDOW_DAYS,
    MAX_SYNC_HISTORY_WINDOW_DAYS,
    SsoDisconnectedError,
    SsoService,
)

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


class SsoStartRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    school_slug: str = Field(alias="schoolSlug", min_length=1, max_length=100)
    provider: SsoProvider


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


class SsoDataFlowCategoryResponse(BaseModel):
    key: str
    description: str
    purpose: str


class SsoConnectionHealthResponse(BaseModel):
    provider: SsoProvider
    status: SsoConnectionStatus
    school_url_slug: str
    school_entry_url: str
    last_connection_error: str | None
    connection_checked_at: datetime | None
    reauthorised_at: datetime | None
    last_successful_sync_at: datetime | None
    next_scheduled_sync_at: datetime | None
    disconnected_at: datetime | None
    data_flow: list[SsoDataFlowCategoryResponse]

    @classmethod
    def from_health(
        cls,
        health: SsoConnectionHealth,
    ) -> "SsoConnectionHealthResponse":
        return cls(
            provider=health.provider,
            status=health.status,
            school_url_slug=health.school_url_slug,
            school_entry_url=health.school_entry_url,
            last_connection_error=health.last_connection_error,
            connection_checked_at=health.connection_checked_at,
            reauthorised_at=health.reauthorised_at,
            last_successful_sync_at=health.last_successful_sync_at,
            next_scheduled_sync_at=health.next_scheduled_sync_at,
            disconnected_at=health.disconnected_at,
            data_flow=[
                SsoDataFlowCategoryResponse(
                    key=category.key,
                    description=category.description,
                    purpose=category.purpose,
                )
                for category in health.data_flow
            ],
        )


class RosterSyncIssueResponse(BaseModel):
    id: UUID
    external_reference: str
    description: str
    resolution_hint: str | None


class RosterSyncRunResponse(BaseModel):
    id: UUID
    provider: SsoProvider
    status: RosterSyncStatus
    imported_students: int
    imported_teachers: int
    missing_teacher_class_mappings: int
    failure_reason: str | None
    triggered_manually: bool
    started_at: datetime
    completed_at: datetime | None
    issues: list[RosterSyncIssueResponse]

    @classmethod
    def from_run(cls, run: RosterSyncRunView) -> "RosterSyncRunResponse":
        return cls(
            id=run.id,
            provider=run.provider,
            status=run.status,
            imported_students=run.imported_students,
            imported_teachers=run.imported_teachers,
            missing_teacher_class_mappings=run.missing_teacher_class_mappings,
            failure_reason=run.failure_reason,
            triggered_manually=run.triggered_manually,
            started_at=run.started_at,
            completed_at=run.completed_at,
            issues=[
                RosterSyncIssueResponse(
                    id=issue.id,
                    external_reference=issue.external_reference,
                    description=issue.description,
                    resolution_hint=issue.resolution_hint,
                )
                for issue in run.issues
            ],
        )


class RosterSyncHistoryResponse(BaseModel):
    window_days: int
    successful_runs: int
    failed_runs: int
    runs: list[RosterSyncRunResponse]

    @classmethod
    def from_history(
        cls,
        history: RosterSyncHistory,
    ) -> "RosterSyncHistoryResponse":
        return cls(
            window_days=history.window_days,
            successful_runs=history.successful_runs,
            failed_runs=history.failed_runs,
            runs=[RosterSyncRunResponse.from_run(run) for run in history.runs],
        )


class SsoReauthorisationResponse(BaseModel):
    provider: SsoProvider
    authorization_url: str
    school_entry_url: str

    @classmethod
    def from_reauthorisation(
        cls,
        reauthorisation: SsoReauthorisation,
    ) -> "SsoReauthorisationResponse":
        return cls(
            provider=reauthorisation.provider,
            authorization_url=reauthorisation.authorization_url,
            school_entry_url=reauthorisation.school_entry_url,
        )


class SsoDisconnectRequest(BaseModel):
    """Second of the two confirmations; the first is in the dashboard."""

    confirm: bool = Field(
        description=(
            "Must be true. Disconnecting stops new SSO sign-ins and pauses "
            "roster sync. No account is deleted and no data is removed."
        ),
    )


class SsoDisconnectionResponse(BaseModel):
    provider: SsoProvider
    disconnected_at: datetime
    retained_user_count: int

    @classmethod
    def from_disconnection(
        cls,
        disconnection: SsoDisconnection,
    ) -> "SsoDisconnectionResponse":
        return cls(
            provider=disconnection.provider,
            disconnected_at=disconnection.disconnected_at,
            retained_user_count=disconnection.retained_user_count,
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
ProviderQuery = Annotated[SsoProvider, Query()]


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


@router.post("/auth/sso/start", response_model=SsoStartResponse)
async def start_sso_alias(
    payload: SsoStartRequest,
    service: SsoDependency,
) -> SsoStartResponse:
    return await start_sso(payload.school_slug, payload.provider, service)


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


@router.get("/auth/sso/callback", response_model=SsoCallbackResponse)
async def sso_callback_alias(
    service: SsoDependency,
    provider: ProviderQuery,
    code: str = Query(min_length=1),
    state: str = Query(min_length=3),
) -> SsoCallbackResponse:
    return await sso_callback(provider, service, code, state)


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


@router.get(
    "/admin/sso/status",
    response_model=SsoConnectionHealthResponse,
)
async def sso_connection_status(
    actor: ItSsoDependency,
    service: SsoDependency,
) -> SsoConnectionHealthResponse:
    try:
        health = await service.connection_health(_school_id(actor))
    except LookupError as error:
        raise _sso_not_configured(error) from error
    return SsoConnectionHealthResponse.from_health(health)


@router.get(
    "/admin/sso/roster-sync-history",
    response_model=RosterSyncHistoryResponse,
)
async def roster_sync_history(
    actor: ItSsoDependency,
    service: SsoDependency,
    window_days: int = Query(
        default=DEFAULT_SYNC_HISTORY_WINDOW_DAYS,
        ge=1,
        le=MAX_SYNC_HISTORY_WINDOW_DAYS,
    ),
) -> RosterSyncHistoryResponse:
    history = await service.sync_history(
        school_id=_school_id(actor),
        window_days=window_days,
    )
    return RosterSyncHistoryResponse.from_history(history)


@router.post(
    "/admin/sso/roster-sync",
    response_model=RosterSyncResponse,
)
async def trigger_manual_roster_sync(
    actor: ItSsoDependency,
    service: SsoDependency,
) -> RosterSyncResponse:
    try:
        result = await service.sync_roster_for_school(
            school_id=_school_id(actor),
            triggered_by_user_id=actor.user_id,
        )
    except SsoDisconnectedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "sso_disconnected", "message": str(error)},
        ) from error
    except LookupError as error:
        raise _sso_not_configured(error) from error
    return RosterSyncResponse.from_result(result)


@router.post(
    "/admin/sso/reauthorise",
    response_model=SsoReauthorisationResponse,
)
async def reauthorise_sso(
    actor: ItSsoDependency,
    service: SsoDependency,
) -> SsoReauthorisationResponse:
    try:
        reauthorisation = await service.reauthorise(_school_id(actor))
    except LookupError as error:
        raise _sso_not_configured(error) from error
    return SsoReauthorisationResponse.from_reauthorisation(reauthorisation)


@router.post(
    "/admin/sso/disconnect",
    response_model=SsoDisconnectionResponse,
)
async def disconnect_sso(
    payload: SsoDisconnectRequest,
    actor: ItSsoDependency,
    service: SsoDependency,
) -> SsoDisconnectionResponse:
    if not payload.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "confirmation_required",
                "message": (
                    "Confirm the disconnect to continue. Existing accounts "
                    "are kept and no data is removed."
                ),
            },
        )
    try:
        disconnection = await service.disconnect(
            school_id=_school_id(actor),
            disconnected_by_user_id=actor.user_id,
        )
    except LookupError as error:
        raise _sso_not_configured(error) from error
    return SsoDisconnectionResponse.from_disconnection(disconnection)


def _school_id(actor: PermissionSnapshot) -> UUID:
    if actor.school_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "missing_school_context",
                "message": "A school context is required.",
            },
        )
    return actor.school_id


def _sso_not_configured(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "sso_not_configured",
            "message": str(error),
        },
    )


def _public_sso_error(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "code": "sso_unavailable",
            "message": str(error),
        },
    )
