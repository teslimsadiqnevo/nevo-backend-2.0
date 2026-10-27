"""Durable optional-media work and explicit professional approval."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base


class DeferredLessonMedia(Base):
    __tablename__ = "deferred_lesson_media"
    __table_args__ = (
        Index("ix_deferred_media_claim", "kind", "status", "lease_until"),
        UniqueConstraint("segment_id", "kind", name="uq_deferred_media_segment_kind"),
        CheckConstraint("kind IN ('image', 'audio')", name="ck_deferred_media_kind"),
        CheckConstraint(
            "status IN ('queued','processing','awaiting_review','approved',"
            "'failed','stale','withdrawn')",
            name="ck_deferred_media_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    lesson_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    segment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lesson_segments.id", ondelete="CASCADE")
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    source_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawn_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    withdrawn_by_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    withdrawal_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    withdrawal_reason_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    withdrawal_reason_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    restored_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    restored_by_name: Mapped[str | None] = mapped_column(String(300), nullable=True)


class VisualSafetyRestamp(Base):
    __tablename__ = "visual_safety_restamps"
    __table_args__ = (
        UniqueConstraint("segment_id", "policy_version", name="uq_visual_restamp_segment_policy"),
        Index("ix_visual_restamp_claim", "status", "lease_until"),
        CheckConstraint(
            "status IN ('queued','processing','passed','blocked','failed','stale')",
            name="ck_visual_restamp_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    segment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lesson_segments.id", ondelete="CASCADE"), nullable=False
    )
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(60))
    caption_candidate: Mapped[str | None] = mapped_column(String(300))
    caption_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    caption_approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
