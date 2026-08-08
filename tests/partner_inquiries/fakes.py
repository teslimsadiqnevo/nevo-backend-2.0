from datetime import UTC, datetime
from uuid import uuid4

from nevo.partner_inquiries.entities import (
    PartnerInquiryDraft,
    PartnerInquiryView,
)


class MemoryPartnerInquiryRepository:
    def __init__(self) -> None:
        self.created: list[PartnerInquiryDraft] = []

    async def create(
        self,
        draft: PartnerInquiryDraft,
    ) -> PartnerInquiryView:
        self.created.append(draft)
        return PartnerInquiryView(
            id=uuid4(),
            full_name=draft.full_name,
            school_name=draft.school_name,
            role=draft.role,
            contact=draft.contact,
            contact_method=draft.contact_method,
            message=draft.message,
            created_at=datetime.now(UTC),
        )
