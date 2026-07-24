import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base
from nevo.domain.exports.vocabulary import (
    IepExportShareStatus,
    IepExportStatus,
    StudentRecordEventType,
)

iep_export_status_enum = Enum(
    IepExportStatus,
    name="iep_export_status",
    values_callable=lambda enum: [item.value for item in enum],
)
iep_export_share_status_enum = Enum(
    IepExportShareStatus,
    name="iep_export_share_status",
    values_callable=lambda enum: [item.value for item in enum],
)
student_record_event_type_enum = Enum(
    StudentRecordEventType,
    name="student_record_event_type",
    values_callable=lambda enum: [item.value for item in enum],
)


class IepExport(Base):
    __tablename__ = "iep_exports"
    __table_args__ = (
        CheckConstraint("period_end >= period_start", name="period_order_valid"),
        CheckConstraint(
            "(status = 'final') = (reviewed_by_user_id IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="final_requires_senco_review",
        ),
        Index("ix_iep_exports_student_period", "student_id", "period_start", "period_end"),
        Index("ix_iep_exports_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[IepExportStatus] = mapped_column(
        iep_export_status_enum,
        nullable=False,
        default=IepExportStatus.DRAFT,
        server_default=IepExportStatus.DRAFT.value,
    )
    export_content: Mapped[str] = mapped_column(Text, nullable=False)
    source_summary: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    annotations: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    ai_gateway_call_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("ai_gateway_calls.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class IepExportShare(Base):
    __tablename__ = "iep_export_shares"
    __table_args__ = (
        UniqueConstraint(
            "export_id",
            "parent_id",
            name="uq_iep_export_shares_export_parent",
        ),
        Index("ix_iep_export_shares_parent_shared", "parent_id", "shared_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    export_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("iep_exports.id", ondelete="CASCADE"),
        nullable=False,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    parent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    shared_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[IepExportShareStatus] = mapped_column(
        iep_export_share_status_enum,
        nullable=False,
        default=IepExportShareStatus.SHARED,
        server_default=IepExportShareStatus.SHARED.value,
    )
    shared_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class StudentRecordEvent(Base):
    __tablename__ = "student_record_events"
    __table_args__ = (
        Index("ix_student_record_events_student_created", "student_id", "created_at"),
        Index("ix_student_record_events_export_created", "export_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    export_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("iep_exports.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[StudentRecordEventType] = mapped_column(
        student_record_event_type_enum,
        nullable=False,
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    payload: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
