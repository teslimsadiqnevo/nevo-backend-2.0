from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from nevo.domain.partner_inquiries.vocabulary import (
    PartnerInquiryContactMethod,
    PartnerInquiryRole,
)


@dataclass(frozen=True, slots=True)
class PartnerInquiryDraft:
    full_name: str
    school_name: str
    role: PartnerInquiryRole
    contact: str
    contact_method: PartnerInquiryContactMethod
    message: str | None


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
