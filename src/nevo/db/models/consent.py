import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base
from nevo.db.models.account import consent_type_enum
from nevo.domain.accounts.vocabulary import ConsentType
from nevo.domain.consent.vocabulary import (
    ConsentDeliveryStatus,
    ParentContactMethod,
)

parent_contact_method_enum = Enum(
    ParentContactMethod,
    name="parent_contact_method",
    values_callable=lambda enum: [item.value for item in enum],
)
consent_delivery_status_enum = Enum(
    ConsentDeliveryStatus,
    name="consent_delivery_status",
    values_callable=lambda enum: [item.value for item in enum],
)


class ParentLink(Base):
    __tablename__ = "parent_links"
    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "parent_contact",
            "contact_method",
            name="uq_parent_links_student_contact_method",
        ),
        CheckConstraint(
            "account_created = (parent_id IS NOT NULL)",
            name="account_created_matches_parent",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("schools.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    parent_name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_contact: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_method: Mapped[ParentContactMethod] = mapped_column(
        parent_contact_method_enum,
        nullable=False,
    )
    account_created: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ConsentInvitation(Base):
    __tablename__ = "consent_invitations"
    __table_args__ = (
        UniqueConstraint(
            "token_digest",
            name="uq_consent_invitations_token_digest",
        ),
        CheckConstraint(
            "NOT (accepted_at IS NOT NULL AND revoked_at IS NOT NULL)",
            name="not_accepted_and_revoked",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    parent_link_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("parent_links.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("schools.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class ConsentInvitationItem(Base):
    __tablename__ = "consent_invitation_items"
    __table_args__ = (
        UniqueConstraint(
            "invitation_id",
            "consent_type",
            name="uq_consent_invitation_items_invitation_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    invitation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("consent_invitations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    consent_type: Mapped[ConsentType] = mapped_column(
        consent_type_enum,
        nullable=False,
    )


class ConsentNotificationOutbox(Base):
    __tablename__ = "consent_notification_outbox"
    __table_args__ = (
        UniqueConstraint(
            "invitation_id",
            name="uq_consent_notification_outbox_invitation_id",
        ),
        CheckConstraint(
            "(status = 'sent') = (sent_at IS NOT NULL)",
            name="sent_status_matches_timestamp",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    invitation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("consent_invitations.id", ondelete="CASCADE"),
        nullable=False,
    )
    contact_method: Mapped[ParentContactMethod] = mapped_column(
        parent_contact_method_enum,
        nullable=False,
    )
    destination: Mapped[str] = mapped_column(String(255), nullable=False)
    consent_url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ConsentDeliveryStatus] = mapped_column(
        consent_delivery_status_enum,
        nullable=False,
        default=ConsentDeliveryStatus.QUEUED,
        server_default=ConsentDeliveryStatus.QUEUED.value,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
