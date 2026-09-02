from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from nevo.domain.partner_inquiries.vocabulary import (
    PartnerInquiryContactMethod,
    PartnerInquiryIntent,
    PartnerInquiryRole,
    PartnerInquirySource,
)


@dataclass(frozen=True, slots=True)
class PartnerInquiryDraft:
    full_name: str
    school_name: str
    role: PartnerInquiryRole
    contact: str
    contact_method: PartnerInquiryContactMethod
    message: str | None
    #: TOSSE captures these; the website form does not.
    email: str | None = None
    phone: str | None = None
    student_count: int | None = None
    intent: PartnerInquiryIntent | None = None
    source: PartnerInquirySource = PartnerInquirySource.WEBSITE


@dataclass(frozen=True, slots=True)
class PartnerInquiryView:
    id: UUID
    full_name: str
    school_name: str
    role: PartnerInquiryRole
    contact: str
    contact_method: PartnerInquiryContactMethod
    message: str | None
    created_at: datetime
    #: TOSSE captures these; the website form does not.
    email: str | None = None
    phone: str | None = None
    student_count: int | None = None
    intent: PartnerInquiryIntent | None = None
    source: PartnerInquirySource = PartnerInquirySource.WEBSITE

