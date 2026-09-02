import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, Text, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base
from nevo.domain.partner_inquiries.vocabulary import (
    PartnerInquiryContactMethod,
    PartnerInquiryIntent,
    PartnerInquiryRole,
    PartnerInquirySource,
)

partner_inquiry_role_enum = Enum(
    PartnerInquiryRole,
    name="partner_inquiry_role",
    values_callable=lambda enum: [item.value for item in enum],
)
partner_inquiry_contact_method_enum = Enum(
    PartnerInquiryContactMethod,
    name="partner_inquiry_contact_method",
    values_callable=lambda enum: [item.value for item in enum],
)
partner_inquiry_intent_enum = Enum(
    PartnerInquiryIntent,
    name="partner_inquiry_intent",
    values_callable=lambda enum: [item.value for item in enum],
)
partner_inquiry_source_enum = Enum(
    PartnerInquirySource,
    name="partner_inquiry_source",
    values_callable=lambda enum: [item.value for item in enum],
)


class PartnerInquiry(Base):
    __tablename__ = "partner_inquiries"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    school_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[PartnerInquiryRole] = mapped_column(
        partner_inquiry_role_enum,
        nullable=False,
    )
    contact: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_method: Mapped[PartnerInquiryContactMethod] = mapped_column(
        partner_inquiry_contact_method_enum,
        nullable=False,
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Added for TOSSE. Nullable so the existing website form, which collects a
    # single contact and no intent, keeps posting unchanged.
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    student_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    intent: Mapped[PartnerInquiryIntent | None] = mapped_column(
        partner_inquiry_intent_enum,
        nullable=True,
    )
    source: Mapped[PartnerInquirySource] = mapped_column(
        partner_inquiry_source_enum,
        nullable=False,
        default=PartnerInquirySource.WEBSITE,
        server_default=PartnerInquirySource.WEBSITE.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
