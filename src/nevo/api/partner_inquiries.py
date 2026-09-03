import csv
import io
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from nevo.api.permissions import RequireScope
from nevo.domain.partner_inquiries.vocabulary import (
    PartnerInquiryContactMethod,
    PartnerInquiryIntent,
    PartnerInquiryRole,
    PartnerInquirySource,
    parse_role,
)
from nevo.domain.permissions.vocabulary import PermissionScope
from nevo.partner_inquiries.entities import PartnerInquiryView
from nevo.partner_inquiries.errors import PartnerInquiryError
from nevo.partner_inquiries.service import PartnerInquiryService
from nevo.permissions.entities import PermissionSnapshot

router = APIRouter(prefix="/api/v1", tags=["partner inquiries"])
# Mounted at exactly the path agreed with the frontend for the event, rather
# than under /api/v1: the QR code is printed once and the console is already
# built against this.
tosse_router = APIRouter(prefix="/api/tosse", tags=["partner inquiries"])


class PartnerInquiryRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    school_name: str = Field(min_length=2, max_length=255)
    role: PartnerInquiryRole
    contact: str = Field(min_length=3, max_length=255)
    message: str | None = Field(default=None, max_length=2000)


class PartnerInquiryResponse(BaseModel):
    id: UUID
    full_name: str
    school_name: str
    role: PartnerInquiryRole
    contact: str
    contact_method: PartnerInquiryContactMethod
    message: str | None
    created_at: datetime

    @classmethod
    def from_view(cls, view: PartnerInquiryView) -> "PartnerInquiryResponse":
        return cls(
            id=view.id,
            full_name=view.full_name,
            school_name=view.school_name,
            role=view.role,
            contact=view.contact,
            contact_method=view.contact_method,
            message=view.message,
            created_at=view.created_at,
        )


def get_partner_inquiry_service(request: Request) -> PartnerInquiryService:
    service = getattr(request.app.state, "partner_inquiry_service", None)
    if not isinstance(service, PartnerInquiryService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_unavailable",
                "message": (
                    "Partner inquiry services are temporarily unavailable."
                ),
            },
        )
    return service


PartnerInquiryServiceDependency = Annotated[
    PartnerInquiryService,
    Depends(get_partner_inquiry_service),
]


@router.post(
    "/partner-inquiries",
    response_model=PartnerInquiryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_partner_inquiry(
    payload: PartnerInquiryRequest,
    service: PartnerInquiryServiceDependency,
) -> PartnerInquiryResponse:
    try:
        view = await service.submit(
            full_name=payload.full_name,
            school_name=payload.school_name,
            role=payload.role,
            contact=payload.contact,
            message=payload.message,
        )
    except PartnerInquiryError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": error.code, "message": error.public_message},
        ) from error
    return PartnerInquiryResponse.from_view(view)


# --- TOSSE lead capture ----------------------------------------------------
# Public and unauthenticated by design: a school scans a QR code at the stand
# and lands straight on the form. Stored alongside website inquiries and
# tagged by source, so there is one place to look for leads afterwards.


class TosseInterestRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    full_name: str = Field(alias="name", min_length=2, max_length=255)
    #: Accepted as free text, not the enum. The page sends the dropdown's
    #: display label, and a lead at a stand is worth more than a tidy request
    #: shape - an unfamiliar role is recorded as "other" rather than rejected.
    role: str = Field(min_length=1, max_length=120)
    school_name: str = Field(alias="schoolName", min_length=2, max_length=255)
    student_count: int = Field(alias="studentCount", gt=0, le=100_000)
    phone: str = Field(min_length=6, max_length=50)
    email: EmailStr
    intent: PartnerInquiryIntent
    message: str | None = Field(default=None, max_length=2000)


class TosseInterestResponse(BaseModel):
    """Deliberately thin.

    The confirmation screen needs to know it worked, not to be handed back the
    lead. Returning less means less to leak from a public endpoint.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    #: SCRUM-117 specifies this exact field; the page treats its absence as a
    #: failure and shows the retry notice instead of the confirmation.
    status: Literal["received"] = "received"
    received: bool = True


@tosse_router.post(
    "/interest",
    response_model=TosseInterestResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["partner inquiries"],
)
async def submit_tosse_interest(
    payload: TosseInterestRequest,
    service: PartnerInquiryServiceDependency,
) -> TosseInterestResponse:
    """Capture a founding-partner lead from the TOSSE landing page.

    Public and unauthenticated: the visitor is a headteacher at a stand who
    has just scanned a QR code, so anything that turns a real lead into an
    error is a lead lost with a Nevo rep watching.
    """
    try:
        view = await service.submit(
            full_name=payload.full_name,
            school_name=payload.school_name,
            role=parse_role(payload.role) or PartnerInquiryRole.OTHER,
            email=str(payload.email),
            phone=payload.phone,
            student_count=payload.student_count,
            intent=payload.intent,
            message=payload.message,
            source=PartnerInquirySource.TOSSE_2026,
        )
    except PartnerInquiryError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": error.code, "message": error.public_message},
        ) from error
    return TosseInterestResponse(id=view.id)


class LeadListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    leads: list["LeadResponse"]
    total: int


class LeadResponse(BaseModel):
    """A lead as the person working the stand needs to see it."""

    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    full_name: str = Field(alias="fullName")
    school_name: str = Field(alias="schoolName")
    role: PartnerInquiryRole
    student_count: int | None = Field(alias="studentCount")
    email: str | None
    phone: str | None
    intent: PartnerInquiryIntent | None
    message: str | None
    source: PartnerInquirySource
    created_at: datetime = Field(alias="createdAt")

    @classmethod
    def from_view(cls, view: PartnerInquiryView) -> "LeadResponse":
        return cls(
            id=view.id,
            full_name=view.full_name,
            school_name=view.school_name,
            role=view.role,
            student_count=view.student_count,
            email=view.email or (view.contact if "@" in view.contact else None),
            phone=view.phone or (None if "@" in view.contact else view.contact),
            intent=view.intent,
            message=view.message,
            source=view.source,
            created_at=view.created_at,
        )


SourceFilter = Annotated[PartnerInquirySource | None, Query(alias="source")]


@router.get("/partner-inquiries", response_model=LeadListResponse)
async def list_partner_inquiries(
    actor: Annotated[PermissionSnapshot, Depends(RequireScope(PermissionScope.OVERSIGHT))],
    service: PartnerInquiryServiceDependency,
    source: SourceFilter = None,
) -> LeadListResponse:
    """Every lead, newest first. Filter by source for one event's leads."""
    views = await service.recent(source=source)
    return LeadListResponse(
        leads=[LeadResponse.from_view(view) for view in views],
        total=len(views),
    )


@router.get("/partner-inquiries.csv")
async def export_partner_inquiries(
    actor: Annotated[PermissionSnapshot, Depends(RequireScope(PermissionScope.OVERSIGHT))],
    service: PartnerInquiryServiceDependency,
    source: SourceFilter = None,
) -> Response:
    """The same leads as a spreadsheet.

    This is the system of record after the event, not the inbox: alerts are
    best effort and one that fails to send is not a lead that failed to save.
    """
    views = await service.recent(source=source)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "Received",
            "School",
            "Name",
            "Role",
            "Students",
            "Email",
            "Phone",
            "Interested in",
            "Message",
            "Source",
        ]
    )
    for view in views:
        lead = LeadResponse.from_view(view)
        writer.writerow(
            [
                f"{lead.created_at:%Y-%m-%d %H:%M}",
                lead.school_name,
                lead.full_name,
                lead.role.value.replace("_", " "),
                lead.student_count if lead.student_count is not None else "",
                lead.email or "",
                lead.phone or "",
                lead.intent.value.replace("_", " ") if lead.intent else "",
                lead.message or "",
                lead.source.value,
            ]
        )
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="nevo-leads-{stamp}.csv"',
        },
    )
