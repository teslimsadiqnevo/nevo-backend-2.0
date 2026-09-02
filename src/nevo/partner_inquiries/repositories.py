from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.partner_inquiry import PartnerInquiry
from nevo.domain.partner_inquiries.vocabulary import PartnerInquirySource
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
                email=draft.email,
                phone=draft.phone,
                student_count=draft.student_count,
                intent=draft.intent,
                source=draft.source,
            )
            session.add(record)
            await session.flush()
            return self._view(record)

    async def recent(
        self,
        *,
        source: PartnerInquirySource | None = None,
        limit: int = 500,
    ) -> list[PartnerInquiryView]:
        """Newest first, optionally for one source."""
        query = select(PartnerInquiry).order_by(PartnerInquiry.created_at.desc())
        if source is not None:
            query = query.where(PartnerInquiry.source == source)
        async with self._sessions() as session:
            rows = (await session.scalars(query.limit(limit))).all()
        return [self._view(record) for record in rows]

    @staticmethod
    def _view(record: PartnerInquiry) -> PartnerInquiryView:
        return PartnerInquiryView(
            id=record.id,
            full_name=record.full_name,
            school_name=record.school_name,
            role=record.role,
            contact=record.contact,
            email=record.email,
            phone=record.phone,
            student_count=record.student_count,
            intent=record.intent,
            source=record.source,
            contact_method=record.contact_method,
            message=record.message,
            created_at=record.created_at,
        )
