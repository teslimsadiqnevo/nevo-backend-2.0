import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Text, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base
from nevo.domain.attention_flags.vocabulary import AttentionFlagType

attention_flag_type_enum = Enum(
    AttentionFlagType,
    name="attention_flag_type",
    values_callable=lambda enum: [item.value for item in enum],
)


class AttentionFlag(Base):
    __tablename__ = "attention_flags"
    __table_args__ = (
        Index("ix_attention_flags_student_generated", "student_id", "generated_at"),
        Index("ix_attention_flags_type_generated", "flag_type", "generated_at"),
        Index(
            "ix_attention_flags_open_student",
            "student_id",
            postgresql_where=text("acknowledged_at IS NULL"),
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
    flag_type: Mapped[AttentionFlagType] = mapped_column(
        attention_flag_type_enum,
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class Escalation(Base):
    __tablename__ = "escalations"
    __table_args__ = (
        Index("ix_escalations_student_generated", "student_id", "generated_at"),
        Index("ix_escalations_teacher_generated", "teacher_id", "generated_at"),
        Index(
            "ix_escalations_unacknowledged_student",
            "student_id",
            postgresql_where=text("acknowledged_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    attention_flag_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("attention_flags.id", ondelete="SET NULL"),
        nullable=True,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    teacher_note: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class InterventionRecommendation(Base):
    __tablename__ = "intervention_recommendations"
    __table_args__ = (
        Index(
            "ix_intervention_recommendations_student_generated",
            "student_id",
            "generated_at",
        ),
        Index(
            "ix_intervention_recommendations_flag_generated",
            "attention_flag_id",
            "generated_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    attention_flag_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("attention_flags.id", ondelete="CASCADE"),
        nullable=False,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    recommendation_text: Mapped[str] = mapped_column(Text, nullable=False)
    ai_gateway_call_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("ai_gateway_calls.id", ondelete="SET NULL"),
        nullable=True,
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
