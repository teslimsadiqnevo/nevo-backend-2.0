from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.partner_inquiries.repositories import (
    SqlAlchemyPartnerInquiryRepository,
)
from nevo.partner_inquiries.service import PartnerInquiryService


def build_partner_inquiry_service(
    sessions: async_sessionmaker[AsyncSession],
) -> PartnerInquiryService:
    return PartnerInquiryService(
        repository=SqlAlchemyPartnerInquiryRepository(sessions),
    )
