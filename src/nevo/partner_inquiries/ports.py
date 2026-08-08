from typing import Protocol

from nevo.partner_inquiries.entities import (
    PartnerInquiryDraft,
    PartnerInquiryView,
)


class PartnerInquiryRepository(Protocol):
    async def create(
        self,
        draft: PartnerInquiryDraft,
    ) -> PartnerInquiryView: ...
