import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base


class ContentSafetyEvent(Base):
    __tablename__ = "content_safety_events"
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    school_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("schools.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE")
    )
    phase: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(20))
    categories: Mapped[list] = mapped_column(JSONB)
    policy_version: Mapped[str] = mapped_column(String(60))
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: The text behind a finding we allowed through.
    #:
    #: Lydia's condition on Option A: a privacy_abuse finding on Nevo's own
    #: lesson text no longer blocks, and is still recorded with the text so a
    #: true positive would show. Null for everything else - storing the
    #: material for every decision would keep every lesson several times
    #: over, and the ones worth reading are the ones we did not act on.
    allowed_material: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
