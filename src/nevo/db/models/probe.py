"""The domain probe: items, and what a child answered.

The probe was specified as an adaptive knowledge probe that seeds the knowledge
graph entry point per subject. It was not one: sixteen items sat hardcoded in
the front end with a local answer key, no difficulty attached and no adaptation
possible. An answer key on the device is also a probe a child can read.

Items are generated from the lessons teachers upload, per subject, so the probe
tests the concepts in that school's own library rather than a curriculum we
picked for them. They are scoped to the school for the same reason: one
school's items never serve another school's children.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base


class ProbeItem(Base):
    """One question, and the answer that never leaves the server."""

    __tablename__ = "probe_items"
    __table_args__ = (
        Index("ix_probe_items_school_subject", "school_id", "school_subject_id"),
        Index("ix_probe_items_difficulty", "school_subject_id", "difficulty"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    school_subject_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("school_subjects.id", ondelete="CASCADE"), nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    #: ``[{"value": "a", "label": "..."}]``. Shown to the child.
    options: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    #: Never serialised to a device. The client sends what the child picked and
    #: the server says whether the next item is harder or easier; it never says
    #: which option was right, because a probe whose key is on the device
    #: measures nothing.
    correct_option: Mapped[str] = mapped_column(String(80), nullable=False)
    #: Which year group this was written for.
    band: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: The concept in the school's own material this maps to, and the lesson it
    #: was generated from - so an item can be traced back to the teaching it
    #: came from, and retired when that lesson is.
    concept_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("lessons.id", ondelete="SET NULL"), nullable=True
    )
    #: 0 easiest, 1 hardest. A starting estimate, and the column exists to be
    #: updated from real response data: difficulty is learned from how children
    #: actually answer rather than assigned once by whoever wrote the item.
    difficulty: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.5")
    #: How that estimate has been earned so far, so a difficulty resting on
    #: four answers is not treated like one resting on four hundred.
    times_answered: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    times_correct: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    retired: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProbeResponse(Base):
    """What one child answered, and where the probe had got to.

    Kept because difficulty is learned from it. Without the responses the
    difficulty column can only ever hold the estimate it was written with.
    """

    __tablename__ = "probe_responses"
    __table_args__ = (
        Index("ix_probe_responses_student_subject", "student_id", "school_subject_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    school_subject_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("school_subjects.id", ondelete="CASCADE"), nullable=False
    )
    probe_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("probe_items.id", ondelete="CASCADE"), nullable=False
    )
    chosen_option: Mapped[str] = mapped_column(String(80), nullable=False)
    correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    #: The difficulty of the item when it was served, so a later recalibration
    #: does not rewrite the history of what this child was actually asked.
    difficulty_at_the_time: Mapped[float] = mapped_column(Float, nullable=False)
    answered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
