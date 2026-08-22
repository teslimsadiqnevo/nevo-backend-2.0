import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base
from nevo.domain.mastery.vocabulary import FailureAttribution

failure_attribution_enum = Enum(
    FailureAttribution,
    name="mastery_failure_attribution",
    values_callable=lambda enum: [item.value for item in enum],
)


class StudentConceptMastery(Base):
    __tablename__ = "student_concept_mastery"
    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "concept_id",
            name="uq_student_concept_mastery_student_concept",
        ),
        CheckConstraint(
            "mastery_probability_concept BETWEEN 0 AND 1",
            name="mastery_probability_concept_range",
        ),
        CheckConstraint(
            "mastery_probability_reading BETWEEN 0 AND 1",
            name="mastery_probability_reading_range",
        ),
        CheckConstraint(
            "guess_probability BETWEEN 0 AND 1",
            name="guess_probability_range",
        ),
        CheckConstraint(
            "slip_probability BETWEEN 0 AND 1",
            name="slip_probability_range",
        ),
        CheckConstraint("practice_count >= 0", name="practice_count_nonnegative"),
        Index("ix_student_concept_mastery_student", "student_id"),
        Index("ix_student_concept_mastery_concept", "concept_id"),
        Index(
            "ix_student_concept_mastery_student_concept",
            "student_id",
            "concept_id",
        ),
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
    concept_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    mastery_probability_concept: Mapped[float] = mapped_column(nullable=False)
    mastery_probability_reading: Mapped[float] = mapped_column(nullable=False)
    attention_weights: Mapped[dict[str, float]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    guess_probability: Mapped[float] = mapped_column(
        nullable=False,
        default=0.2,
        server_default="0.2",
    )
    slip_probability: Mapped[float] = mapped_column(
        nullable=False,
        default=0.1,
        server_default="0.1",
    )
    practice_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    last_response_correct: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )
    last_failure_attribution: Mapped[FailureAttribution] = mapped_column(
        failure_attribution_enum,
        nullable=False,
        default=FailureAttribution.NONE,
        server_default=FailureAttribution.NONE.value,
    )
    seeding_source: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="default",
        server_default="default",
    )
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class StudentConceptScheduling(Base):
    __tablename__ = "student_concept_scheduling"
    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "concept_id",
            name="uq_student_concept_scheduling_student_concept",
        ),
        CheckConstraint("stability > 0", name="scheduling_stability_positive"),
        CheckConstraint(
            "difficulty BETWEEN 1 AND 10",
            name="scheduling_difficulty_range",
        ),
        CheckConstraint(
            "review_count >= 0",
            name="scheduling_review_count_nonnegative",
        ),
        Index("ix_student_concept_scheduling_student", "student_id"),
        Index("ix_student_concept_scheduling_due", "next_review_due"),
        Index(
            "ix_student_concept_scheduling_student_due",
            "student_id",
            "next_review_due",
        ),
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
    concept_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    stability: Mapped[float] = mapped_column(Float, nullable=False)
    difficulty: Mapped[float] = mapped_column(Float, nullable=False)
    last_review: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    review_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    next_review_due: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
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
