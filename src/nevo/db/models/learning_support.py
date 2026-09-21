"""What Nevo did for a child, dated, and who wrote what on the document.

Two records, both of them about the software rather than about the learner.
The rule from the counsel document holds throughout: the system records what
it did, never what the child is. There is no score, index, rating or forecast
here, and there is nowhere to put one.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base
from nevo.domain.intelligence.vocabulary import AccommodationType
from nevo.domain.learning_support.vocabulary import AccommodationChangeAction

accommodation_type_enum = Enum(
    AccommodationType,
    name="accommodation_type",
    values_callable=lambda enum: [item.value for item in enum],
)
accommodation_change_action_enum = Enum(
    AccommodationChangeAction,
    name="accommodation_change_action",
    values_callable=lambda enum: [item.value for item in enum],
)


class AccommodationChange(Base):
    """One accommodation starting or stopping, and what prompted it.

    Accommodations were inferred fresh every time anybody asked, so the
    learning support surface could say what is true today and never what
    changed in March or why. A row per change is the dated record: it is a
    log of Nevo's own decisions, which is exactly the thing a school and a
    regulator are entitled to read.
    """

    __tablename__ = "accommodation_changes"
    __table_args__ = (
        Index(
            "ix_accommodation_changes_student_time",
            "student_id",
            "occurred_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    accommodation: Mapped[AccommodationType] = mapped_column(
        accommodation_type_enum,
        nullable=False,
    )
    action: Mapped[AccommodationChangeAction] = mapped_column(
        accommodation_change_action_enum,
        nullable=False,
    )
    #: What Nevo saw that led to this, in the vocabulary the adaptation log
    #: already uses. Never a description of the child.
    prompted_by: Mapped[str] = mapped_column(String(120), nullable=False)
    #: How many lessons the pattern was seen across, so a reader can tell a
    #: change made on one bad afternoon from one made on a term's evidence.
    observed_over_lessons: Mapped[int | None] = mapped_column(nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ExportAnnotation(Base):
    """A note a member of staff wrote on a child's document.

    Kept as rows rather than inside the export's JSON because the distinction
    is the point: these words are the school's, the export's own text is
    Nevo's, and a parent or a regulator reading the document should never
    have to guess which is which. A row carries its author and its time, and
    neither is taken from the client.
    """

    __tablename__ = "export_annotations"
    __table_args__ = (
        Index("ix_export_annotations_export", "export_id", "created_at"),
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
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    #: The author's name as it stood when they wrote it. A document shared
    #: with a parent should still name whoever wrote the note after they
    #: leave the school.
    author_name: Mapped[str] = mapped_column(String(255), nullable=False)
    author_role: Mapped[str] = mapped_column(String(40), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
