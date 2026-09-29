"""What a class is taught, what a teacher teaches, and who teaches what.

Three tables and one rule.

The rule is that everything references ``school_subjects`` and nothing
references the canonical list directly. A school's list always has a row per
subject it uses, whether that subject came from Nevo's list or the school typed
it. That is what makes a merge free: pointing a school's "Maths" row at
canonical Mathematics changes what the row resolves to and touches none of the
records written against it. The alternative - two nullable foreign keys
everywhere and a COALESCE in every query - loses those records the first time
somebody tidies a duplicate.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base
from nevo.domain.subjects.vocabulary import SubjectOrigin, SubjectReviewState

subject_origin_enum = Enum(
    SubjectOrigin,
    name="subject_origin",
    values_callable=lambda enum: [member.value for member in enum],
)

subject_review_state_enum = Enum(
    SubjectReviewState,
    name="subject_review_state",
    values_callable=lambda enum: [member.value for member in enum],
)


class CanonicalSubject(Base):
    """Nevo's own list. One display name, so it reads the same everywhere."""

    __tablename__ = "canonical_subjects"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    #: Stable across renames, because records point at the row and reports
    #: point at the slug.
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SchoolSubject(Base):
    """One subject on one school's list.

    Exists for canonical subjects too, not only for a school's own additions.
    That is deliberate: it gives every reference in the product a single
    foreign key, and it is what lets a near-duplicate be merged later without
    rewriting the mastery records already filed against it.
    """

    __tablename__ = "school_subjects"
    __table_args__ = (
        # One row per subject per school, whichever way it arrived.
        UniqueConstraint("school_id", "normalised_name", name="uq_school_subjects_name"),
        Index("ix_school_subjects_school", "school_id"),
        Index(
            "ix_school_subjects_review",
            "review_state",
            postgresql_where=text("origin = 'school'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    #: What the school typed, kept as they typed it. Shown back to them in the
    #: review queue, because "Maths Dept" tells you something about the school.
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    #: Case and spacing folded, for the uniqueness that stops one school
    #: holding "Maths" and "maths " as two subjects.
    normalised_name: Mapped[str] = mapped_column(String(120), nullable=False)
    origin: Mapped[SubjectOrigin] = mapped_column(subject_origin_enum, nullable=False)
    #: Set when this row is one of Nevo's, and set later when a school's own is
    #: merged into one. Null means the school's own name is what it resolves to.
    canonical_subject_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("canonical_subjects.id", ondelete="RESTRICT"), nullable=True
    )
    review_state: Mapped[SubjectReviewState] = mapped_column(
        subject_review_state_enum,
        nullable=False,
        server_default=SubjectReviewState.PENDING.value,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ClassSubject(Base):
    """A class's scheme of work: stated once per class, authoritative for it."""

    __tablename__ = "class_subjects"
    __table_args__ = (
        UniqueConstraint("class_id", "school_subject_id", name="uq_class_subjects"),
        Index("ix_class_subjects_subject", "school_subject_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("classes.id", ondelete="CASCADE"), nullable=False
    )
    school_subject_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("school_subjects.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TeacherSubject(Base):
    """What this person teaches. Not where they teach it.

    Two different facts, and only the second was ever modelled. Most teachers
    carry one of these, some carry several.
    """

    __tablename__ = "teacher_subjects"
    __table_args__ = (
        UniqueConstraint("teacher_id", "school_subject_id", name="uq_teacher_subjects"),
        Index("ix_teacher_subjects_subject", "school_subject_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    school_subject_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("school_subjects.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
