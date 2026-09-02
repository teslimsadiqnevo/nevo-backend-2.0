from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.notifications.email import ResendEmailDelivery
from nevo.partner_inquiries.notifier import LeadEmailNotifier
from nevo.partner_inquiries.repositories import (
    SqlAlchemyPartnerInquiryRepository,
)
from nevo.partner_inquiries.service import PartnerInquiryService


def build_partner_inquiry_service(
    sessions: async_sessionmaker[AsyncSession],
    *,
    delivery: ResendEmailDelivery | None = None,
) -> PartnerInquiryService:
    return PartnerInquiryService(
        repository=SqlAlchemyPartnerInquiryRepository(sessions),
        notifier=LeadEmailNotifier(delivery=delivery) if delivery else None,
    )
