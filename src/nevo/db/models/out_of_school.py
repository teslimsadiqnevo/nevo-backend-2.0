"""Learner-reported work outside school, never treated as a marked answer."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base


class OutOfSchoolLearning(Base):
    __tablename__ = "out_of_school_learning"
    __table_args__ = (
        Index("ix_out_of_school_learning_student_created", "student_id", "created_at"),
        UniqueConstraint("client_event_id", name="uq_out_of_school_client_event"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    student_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    concept_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False)
    activity_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    client_event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
