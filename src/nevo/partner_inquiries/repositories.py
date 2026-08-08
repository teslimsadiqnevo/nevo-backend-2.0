from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.partner_inquiry import PartnerInquiry
from nevo.partner_inquiries.entities import (
    PartnerInquiryDraft,
    PartnerInquiryView,
)


class SqlAlchemyPartnerInquiryRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(
        self,
        draft: PartnerInquiryDraft,
    ) -> PartnerInquiryView:
        async with self._sessions.begin() as session:
            record = PartnerInquiry(
                id=uuid4(),
                full_name=draft.full_name,
                school_name=draft.school_name,
                role=draft.role,
                contact=draft.contact,
                contact_method=draft.contact_method,
                message=draft.message,
            )
            session.add(record)
            await session.flush()
            return self._view(record)

    @staticmethod
    def _view(record: PartnerInquiry) -> PartnerInquiryView:
        return PartnerInquiryView(
            id=record.id,
            full_name=record.full_name,
            school_name=record.school_name,
            role=record.role,
            contact=record.contact,
            contact_method=record.contact_method,
            message=record.message,
            created_at=record.created_at,
        )
