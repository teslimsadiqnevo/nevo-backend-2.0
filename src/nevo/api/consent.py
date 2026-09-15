from dataclasses import asdict
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from nevo.api.auth import PrincipalDependency
from nevo.api.casing import CAMEL_CONFIG
from nevo.api.permissions import RequireScope
from nevo.consent.entities import (
    ConsentActor,
    ConsentGate,
    ConsentRecordView,
    ParentConsentCompletion,
    ParentInvitationView,
    ParentLinkView,
    ParentRightLogEntry,
    QueuedParentConsentRequest,
)
from nevo.consent.errors import (
    ConsentError,
    ConsentRequiredError,
    ConsentWithdrawnError,
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
    ParentRightType,
)
from nevo.domain.permissions.vocabulary import PermissionScope
from nevo.permissions.entities import PermissionSnapshot

router = APIRouter(prefix="/api/v1", tags=["consent"])


class SchoolConfirmationRequest(BaseModel):
    model_config = CAMEL_CONFIG

    student_id: UUID
    consent_types: set[ConsentType] = Field(min_length=1)
    confirmed_via: ConsentMethod


class ConsentRecordResponse(BaseModel):
    model_config = CAMEL_CONFIG

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
    model_config = CAMEL_CONFIG

    parent_name: str = Field(min_length=2, max_length=255)
    parent_contact: str = Field(min_length=3, max_length=255)
    contact_method: ParentContactMethod
    consent_types: set[ConsentType] = Field(
        default_factory=lambda: {ConsentType.DATA_PROCESSING},
        min_length=1,
    )


class QueuedParentConsentResponse(BaseModel):
    model_config = CAMEL_CONFIG

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
    model_config = CAMEL_CONFIG

    invitation_id: UUID
    parent_link_id: UUID
    parent_id: UUID
    student_id: UUID
    confirmed_types: list[ConsentType]
    completed_at: datetime
    receipt_sent_to: ParentContactMethod | None = None

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
            receipt_sent_to=completion.receipt_sent_to,
        )


class ParentLinkResponse(BaseModel):
    model_config = CAMEL_CONFIG

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


class ParentConsentInvitationResponse(BaseModel):
    """Everything D01b must name before a parent can consent informedly."""

    model_config = ConfigDict(populate_by_name=True)

    invitation_id: UUID = Field(alias="invitationId")
    student_first_name: str = Field(alias="studentFirstName")
    school_name: str = Field(alias="schoolName")
    school_phone: str | None = Field(alias="schoolPhone")
    school_email: str | None = Field(alias="schoolEmail")
    parent_name: str = Field(alias="parentName")
    #: What the sign-in screen pre-fills.
    parent_contact: str = Field(alias="parentContact")
    parent_contact_method: ParentContactMethod = Field(alias="parentContactMethod")
    status: ConsentStatus
    consent_types: list[ConsentType] = Field(alias="consentTypes")
    expires_at: datetime = Field(alias="expiresAt")
    decided_at: datetime | None = Field(alias="decidedAt")

    @classmethod
    def from_invitation(
        cls,
        invitation: ParentInvitationView,
    ) -> "ParentConsentInvitationResponse":
        return cls(
            invitationId=invitation.invitation_id,
            studentFirstName=invitation.student_first_name,
            schoolName=invitation.school_name,
            schoolPhone=invitation.school_phone,
            schoolEmail=invitation.school_email,
            parentName=invitation.parent_name,
            parentContact=invitation.parent_contact,
            parentContactMethod=invitation.parent_contact_method,
            status=invitation.status,
            consentTypes=sorted(invitation.consent_types, key=lambda item: item.value),
            expiresAt=invitation.expires_at,
            decidedAt=invitation.decided_at,
        )


class ConsentGateResponse(BaseModel):
    model_config = CAMEL_CONFIG

    student_id: UUID
    granted: bool
    blocked: bool
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
    "/consents/parent/{token}",
    response_model=ParentConsentInvitationResponse,
    responses={
        404: {
            "description": "The consent link is unknown, revoked, or expired",
        }
    },
)
async def inspect_parent_consent(
    token: str,
    service: ConsentServiceDependency,
) -> ParentConsentInvitationResponse:
    """Resolve a parent's consent token into the screen it has to render.

    Unauthenticated by design - the token is the credential, exactly as it is
    for the join link. It is scoped to one child, so it reveals only the names
    the parent was already told in the message that carried it.
    """
    invitation = await service.parent_invitation(token=token)
    if invitation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": InvalidConsentInvitationError.code,
                "message": InvalidConsentInvitationError.public_message,
            },
        )
    return ParentConsentInvitationResponse.from_invitation(invitation)


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


class ParentRightLogRow(BaseModel):
    """One entry in a school's record of rights parents have exercised."""

    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    student_id: UUID = Field(alias="studentId")
    student_name: str = Field(alias="studentName")
    parent_id: UUID = Field(alias="parentId")
    parent_name: str = Field(alias="parentName")
    request_type: ParentRightType = Field(alias="requestType")
    reason_recorded: bool = Field(
        alias="reasonRecorded",
        description=(
            "Whether the parent gave a reason. The text itself is not served: "
            "it is free text a parent wrote about their own child, and listing "
            "it would disclose family circumstances to every admin who opens "
            "the screen."
        ),
    )
    status: str
    created_at: datetime = Field(alias="createdAt")
    resolved_at: datetime | None = Field(alias="resolvedAt")

    @classmethod
    def from_entry(cls, entry: ParentRightLogEntry) -> "ParentRightLogRow":
        return cls(
            id=entry.id,
            studentId=entry.student_id,
            studentName=entry.student_name,
            parentId=entry.parent_id,
            parentName=entry.parent_name,
            requestType=entry.request_type,
            reasonRecorded=entry.reason_recorded,
            status=entry.status,
            createdAt=entry.created_at,
            resolvedAt=entry.resolved_at,
        )


class ParentRightLogResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    entries: list[ParentRightLogRow]
    total: int
    limit: int
    offset: int


@router.get("/consents/rights-log", response_model=ParentRightLogResponse)
async def parent_rights_log(
    actor: SencoDependency,
    service: ConsentServiceDependency,
    student_id: Annotated[UUID | None, Query(alias="studentId")] = None,
    request_type: Annotated[
        ParentRightType | None,
        Query(alias="requestType", description="Show only this kind of request."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ParentRightLogResponse:
    """What parents have asked of this school, newest first.

    The requests were being recorded and never read back, so a school had no
    way to show what had been asked of it - which is the thing NDPA expects a
    school to be able to produce.
    """
    try:
        entries, total = await service.parent_rights_log(
            consent_actor(actor),
            student_id=student_id,
            request_type=request_type,
            limit=limit,
            offset=offset,
        )
    except ConsentError as error:
        raise public_consent_error(error) from error
    return ParentRightLogResponse(
        entries=[ParentRightLogRow.from_entry(entry) for entry in entries],
        total=total,
        limit=min(max(limit, 1), 100),
        offset=max(offset, 0),
    )


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


async def require_learning_consent_if_student(
    request: Request,
    principal: PrincipalDependency,
) -> ConsentGate | None:
    """Stop a withdrawn learner, and nobody else.

    A parent who withdraws is told it suspends their child's access
    immediately, so something has to act on that, and until now nothing did:
    the gate was readable and never enforced. It goes on the endpoints that
    do the processing - starting a lesson, recording progress, taking a
    lesson offline, asking Nevo a question - and not on reads, so the client
    can still load the screen that explains why learning has stopped.

    Only an explicit withdrawal blocks. A learner whose consent nobody has
    recorded yet carries on, which is the standing ruling: that gap belongs
    to the school, not to the child.
    """

    if principal.role != "student":
        # Teachers and admins share several of these endpoints and have their
        # own authorisation. A pupil's consent has nothing to say about them,
        # and their access should not depend on the consent service being up,
        # which is why it is only reached for a learner.
        return None
    service = get_consent_service(request)
    try:
        return await service.require_student_consent(principal)
    except ConsentError as error:
        raise public_consent_error(error) from error


StudentLearningConsent = Annotated[
    ConsentGate | None,
    Depends(require_learning_consent_if_student),
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
            ConsentWithdrawnError,
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
