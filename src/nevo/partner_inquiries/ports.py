from typing import Protocol

from nevo.domain.partner_inquiries.vocabulary import PartnerInquirySource
from nevo.partner_inquiries.entities import (
    PartnerInquiryDraft,
    PartnerInquiryView,
)


class PartnerInquiryRepository(Protocol):
    async def recent(
        self,
        *,
        source: PartnerInquirySource | None = None,
        limit: int = 500,
    ) -> list[PartnerInquiryView]: ...

    async def create(
        self,
        draft: PartnerInquiryDraft,
    ) -> PartnerInquiryView: ...
