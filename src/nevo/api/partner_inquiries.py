from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from nevo.domain.partner_inquiries.vocabulary import (
    PartnerInquiryContactMethod,
    PartnerInquiryRole,
)
from nevo.partner_inquiries.entities import PartnerInquiryView
from nevo.partner_inquiries.errors import PartnerInquiryError
from nevo.partner_inquiries.service import PartnerInquiryService

router = APIRouter(prefix="/api/v1", tags=["partner inquiries"])


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
