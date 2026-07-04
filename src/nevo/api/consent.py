from dataclasses import asdict
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from nevo.api.auth import PrincipalDependency
from nevo.api.permissions import RequireScope
from nevo.consent.entities import (
    ConsentActor,
    ConsentGate,
    ConsentRecordView,
    ParentConsentCompletion,
    ParentLinkView,
    QueuedParentConsentRequest,
)
from nevo.consent.errors import (
    ConsentError,
    ConsentRequiredError,
    InvalidConsentInvitationError,
    ParentAccountConflictError,
    StudentConsentAccessError,
    StudentNotFoundError,
)
from nevo.consent.service import ConsentService
from nevo.domain.accounts.vocabulary import (
    ConsentMethod,
    ConsentStatus,
    ConsentType,
)
from nevo.domain.consent.vocabulary import (
    ConsentConfirmationSource,
    ConsentDeliveryStatus,
    ParentContactMethod,
)
from nevo.domain.permissions.vocabulary import PermissionScope
from nevo.permissions.entities import PermissionSnapshot

router = APIRouter(prefix="/api/v1", tags=["consent"])


class SchoolConfirmationRequest(BaseModel):
    student_id: UUID
    consent_types: set[ConsentType] = Field(min_length=1)
    confirmed_via: ConsentMethod


class ConsentRecordResponse(BaseModel):
    id: UUID
    student_id: UUID
    consent_type: ConsentType
    status: ConsentStatus
    confirmation_source: ConsentConfirmationSource | None
    confirmed_via: ConsentMethod | None
    confirmed_at: datetime | None

    @classmethod
    def from_record(cls, record: ConsentRecordView) -> "ConsentRecordResponse":
        return cls(**asdict(record))


class ParentConsentRequest(BaseModel):
    parent_name: str = Field(min_length=2, max_length=255)
    parent_contact: str = Field(min_length=3, max_length=255)
    contact_method: ParentContactMethod
    consent_types: set[ConsentType] = Field(
        default_factory=lambda: {ConsentType.DATA_PROCESSING},
        min_length=1,
    )


class QueuedParentConsentResponse(BaseModel):
    invitation_id: UUID
    parent_link_id: UUID
    student_id: UUID
    consent_types: list[ConsentType]
    delivery_status: ConsentDeliveryStatus
    expires_at: datetime

    @classmethod
    def from_request(
        cls,
        request: QueuedParentConsentRequest,
    ) -> "QueuedParentConsentResponse":
        return cls(
            invitation_id=request.invitation_id,
            parent_link_id=request.parent_link_id,
            student_id=request.student_id,
            consent_types=sorted(
                request.consent_types,
                key=lambda item: item.value,
            ),
            delivery_status=request.delivery_status,
            expires_at=request.expires_at,
        )


class CompleteParentConsentRequest(BaseModel):
    token: str = Field(min_length=32, max_length=512)


class ParentConsentCompletionResponse(BaseModel):
    invitation_id: UUID
    parent_link_id: UUID
    parent_id: UUID
    student_id: UUID
    confirmed_types: list[ConsentType]
    completed_at: datetime

    @classmethod
    def from_completion(
        cls,
        completion: ParentConsentCompletion,
    ) -> "ParentConsentCompletionResponse":
        return cls(
            invitation_id=completion.invitation_id,
            parent_link_id=completion.parent_link_id,
            parent_id=completion.parent_id,
            student_id=completion.student_id,
            confirmed_types=sorted(
                completion.confirmed_types,
                key=lambda item: item.value,
            ),
            completed_at=completion.completed_at,
        )


class ParentLinkResponse(BaseModel):
    id: UUID
    school_id: UUID
    student_id: UUID
    parent_id: UUID | None
    parent_name: str
    parent_contact: str
    contact_method: ParentContactMethod
    account_created: bool

    @classmethod
    def from_link(cls, link: ParentLinkView) -> "ParentLinkResponse":
        return cls(**asdict(link))


class ConsentGateResponse(BaseModel):
    student_id: UUID
    granted: bool
    required_type: ConsentType
    status: ConsentStatus

    @classmethod
    def from_gate(cls, gate: ConsentGate) -> "ConsentGateResponse":
        return cls(**asdict(gate))


def get_consent_service(request: Request) -> ConsentService:
    service = getattr(request.app.state, "consent_service", None)
    if not isinstance(service, ConsentService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_unavailable",
                "message": "Consent services are temporarily unavailable.",
            },
        )
    return service


ConsentServiceDependency = Annotated[
    ConsentService,
    Depends(get_consent_service),
]
SencoDependency = Annotated[
    PermissionSnapshot,
    Depends(RequireScope(PermissionScope.SENCO)),
]


@router.post(
    "/consents/school-confirmations",
    response_model=list[ConsentRecordResponse],
)
async def confirm_consent_by_school(
    payload: SchoolConfirmationRequest,
    actor: SencoDependency,
    service: ConsentServiceDependency,
) -> list[ConsentRecordResponse]:
    try:
        records = await service.confirm_by_school(
            consent_actor(actor),
            student_id=payload.student_id,
            consent_types=frozenset(payload.consent_types),
            confirmed_via=payload.confirmed_via,
        )
    except ConsentError as error:
        raise public_consent_error(error) from error
    return [ConsentRecordResponse.from_record(record) for record in records]


@router.post(
    "/students/{student_id}/parent-consent-requests",
    response_model=QueuedParentConsentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_parent_consent(
    student_id: UUID,
    payload: ParentConsentRequest,
    actor: SencoDependency,
    service: ConsentServiceDependency,
) -> QueuedParentConsentResponse:
    try:
        queued = await service.request_parent_consent(
            consent_actor(actor),
            student_id=student_id,
            parent_name=payload.parent_name,
            parent_contact=payload.parent_contact,
            contact_method=payload.contact_method,
            consent_types=frozenset(payload.consent_types),
        )
    except ConsentError as error:
        raise public_consent_error(error) from error
    return QueuedParentConsentResponse.from_request(queued)


@router.post(
    "/consents/parent/complete",
    response_model=ParentConsentCompletionResponse,
)
async def complete_parent_consent(
    payload: CompleteParentConsentRequest,
    service: ConsentServiceDependency,
) -> ParentConsentCompletionResponse:
    try:
        completion = await service.complete_parent_consent(
            token=payload.token,
        )
        if completion is None:
            raise InvalidConsentInvitationError
    except ConsentError as error:
        raise public_consent_error(error) from error
    return ParentConsentCompletionResponse.from_completion(completion)


@router.get(
    "/students/{student_id}/parent-links",
    response_model=list[ParentLinkResponse],
)
async def list_parent_links(
    student_id: UUID,
    actor: SencoDependency,
    service: ConsentServiceDependency,
) -> list[ParentLinkResponse]:
    try:
        links = await service.parent_links(
            consent_actor(actor),
            student_id=student_id,
        )
    except ConsentError as error:
        raise public_consent_error(error) from error
    return [ParentLinkResponse.from_link(link) for link in links]


@router.get(
    "/students/me/consent-gate",
    response_model=ConsentGateResponse,
)
async def my_consent_gate(
    principal: PrincipalDependency,
    service: ConsentServiceDependency,
) -> ConsentGateResponse:
    try:
        gate = await service.student_gate(principal)
    except ConsentError as error:
        raise public_consent_error(error) from error
    return ConsentGateResponse.from_gate(gate)


async def require_learning_consent(
    principal: PrincipalDependency,
    service: ConsentServiceDependency,
) -> ConsentGate:
    try:
        return await service.require_student_consent(principal)
    except ConsentError as error:
        raise public_consent_error(error) from error


LearningConsentDependency = Annotated[
    ConsentGate,
    Depends(require_learning_consent),
]


def consent_actor(snapshot: PermissionSnapshot) -> ConsentActor:
    if snapshot.school_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "missing_school_context",
                "message": "A school context is required.",
            },
        )
    return ConsentActor(
        user_id=snapshot.user_id,
        school_id=snapshot.school_id,
    )


def public_consent_error(error: ConsentError) -> HTTPException:
    status_code = status.HTTP_400_BAD_REQUEST
    if isinstance(error, StudentNotFoundError):
        status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(
        error,
        (
            StudentConsentAccessError,
            ConsentRequiredError,
        ),
    ):
        status_code = status.HTTP_403_FORBIDDEN
    elif isinstance(error, ParentAccountConflictError):
        status_code = status.HTTP_409_CONFLICT
    return HTTPException(
        status_code=status_code,
        detail={
            "code": error.code,
            "message": error.public_message,
        },
    )
