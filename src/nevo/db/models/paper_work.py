"""Minimal marked paper-work evidence; raw typed answers are not retained."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base


class PaperWorkEvidence(Base):
    __tablename__ = "paper_work_evidence"
    __table_args__ = (
        Index("ix_paper_work_evidence_student_created", "student_id", "created_at"),
        UniqueConstraint("client_submission_id", name="uq_paper_work_client_submission"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    student_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("lesson_sessions.id", ondelete="CASCADE"), nullable=False)
    lesson_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False)
    segment_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("lesson_segments.id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[str] = mapped_column(String(160), nullable=False)
    client_submission_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    marks: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
