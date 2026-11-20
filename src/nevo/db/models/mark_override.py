"""A teacher changing a child's mark, recorded so it can never be silent."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base


class LessonMarkOverride(Base):
    """One teacher decision to change how an answer was marked.

    Append-only, and the machine's own mark is kept beside the new one.

    A teacher correcting a mark is right and necessary - an answer can be
    correct in a way a comparison cannot see - but it is also the one write in
    the system where an adult changes the record of what a child did. So it
    is never an in-place edit with nothing left behind: the attempt carries
    the corrected mark so everything downstream reads the truth, and this
    table says who decided, when, what it was before, and why.

    "Why" is required rather than optional. A mark changed without a reason
    is indistinguishable from a mistake, and the person who most needs the
    reason is whoever reads the row months later - a parent asking, or the
    teacher themself.

    T12 / SCRUM-350, 20 November.
    """

    __tablename__ = "lesson_mark_overrides"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(reason)) > 0",
            name="mark_has_a_reason",
        ),
        CheckConstraint(
            "previous_correct IS DISTINCT FROM corrected_to",
            name="mark_changes_the_mark",
        ),
        #: Every override on one attempt, newest first, which is what a
        #: teacher's own screen and an audit both ask for.
        Index("ix_lesson_mark_overrides_attempt", "attempt_id", "occurred_at"),
        #: Every override against one child, for the question a parent asks.
        Index("ix_lesson_mark_overrides_student", "student_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("lesson_question_attempts.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Denormalised from the attempt so the child's history can be read
    #: without joining through it, and so a purge of a child's data reaches
    #: these rows by the same path as everything else.
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("lessons.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: RESTRICT, not SET NULL. An override with no attributable teacher is
    #: not an audit record, so the account cannot be deleted out from under
    #: it - a departing teacher's account is deactivated, not removed.
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    #: How it was marked before. Null where the answer had never been marked
    #: at all, which is a different situation from having been marked wrong.
    previous_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    corrected_to: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
