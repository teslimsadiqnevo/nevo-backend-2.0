import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base


class LessonReviewSignoff(Base):
    __tablename__ = "lesson_review_signoffs"
    __table_args__ = (
        CheckConstraint("kind IN ('key_points', 'rewrites', 'guided_steps', 'checks')", name="kind_valid"),
        Index("ix_lesson_review_signoffs_lesson_kind", "lesson_id", "kind", "approved_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("lessons.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_by_name: Mapped[str] = mapped_column(String(250), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_snapshot: Mapped[list] = mapped_column(JSONB, nullable=False)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
