import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nevo.db.base import Base
from nevo.domain.learner_profiles.vocabulary import (
    ChannelPreferenceStrength,
    ConfidenceLevel,
    ProcessingChannelPreference,
    ProfileChangeSource,
)

confidence_enum = Enum(
    ConfidenceLevel,
    name="profile_confidence",
    values_callable=lambda enum: [item.value for item in enum],
)
processing_channel_enum = Enum(
    ProcessingChannelPreference,
    name="processing_channel_preference",
    values_callable=lambda enum: [item.value for item in enum],
)
channel_strength_enum = Enum(
    ChannelPreferenceStrength,
    name="channel_preference_strength",
    values_callable=lambda enum: [item.value for item in enum],
)
change_source_enum = Enum(
    ProfileChangeSource,
    name="profile_change_source",
    values_callable=lambda enum: [item.value for item in enum],
)


class LearnerProfileDimensionsMixin:
    visual_spatial_preference: Mapped[ChannelPreferenceStrength | None] = mapped_column(
        channel_strength_enum,
        nullable=True,
    )
    visual_spatial_preference_confidence: Mapped[ConfidenceLevel] = mapped_column(
        confidence_enum,
        nullable=False,
        default=ConfidenceLevel.LOW,
        server_default=ConfidenceLevel.LOW.value,
    )
    auditory_preference: Mapped[ChannelPreferenceStrength | None] = mapped_column(
        channel_strength_enum,
        nullable=True,
    )
    auditory_preference_confidence: Mapped[ConfidenceLevel] = mapped_column(
        confidence_enum,
        nullable=False,
        default=ConfidenceLevel.LOW,
        server_default=ConfidenceLevel.LOW.value,
    )
    reading_writing_preference: Mapped[ChannelPreferenceStrength | None] = mapped_column(
        channel_strength_enum,
        nullable=True,
    )
    reading_writing_preference_confidence: Mapped[ConfidenceLevel] = mapped_column(
        confidence_enum,
        nullable=False,
        default=ConfidenceLevel.LOW,
        server_default=ConfidenceLevel.LOW.value,
    )
    interactive_kinesthetic_preference: Mapped[
        ChannelPreferenceStrength | None
    ] = mapped_column(
        channel_strength_enum,
        nullable=True,
    )
    interactive_kinesthetic_preference_confidence: Mapped[
        ConfidenceLevel
    ] = mapped_column(
        confidence_enum,
        nullable=False,
        default=ConfidenceLevel.LOW,
        server_default=ConfidenceLevel.LOW.value,
    )

    # Legacy aggregate channel retained for backward compatibility. SCRUM-24
    # inference uses the four independent channel dimensions above.
    processing_channel_preference: Mapped[ProcessingChannelPreference] = mapped_column(
        processing_channel_enum,
        nullable=False,
        default=ProcessingChannelPreference.UNDETERMINED,
        server_default=ProcessingChannelPreference.UNDETERMINED.value,
    )
    processing_channel_preference_confidence: Mapped[ConfidenceLevel] = mapped_column(
        confidence_enum,
        nullable=False,
        default=ConfidenceLevel.LOW,
        server_default=ConfidenceLevel.LOW.value,
    )
    cognitive_load_threshold: Mapped[int | None] = mapped_column(
        SmallInteger,
        nullable=True,
    )
    cognitive_load_threshold_confidence: Mapped[ConfidenceLevel] = mapped_column(
        confidence_enum,
        nullable=False,
        default=ConfidenceLevel.LOW,
        server_default=ConfidenceLevel.LOW.value,
    )
    processing_speed: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    processing_speed_confidence: Mapped[ConfidenceLevel] = mapped_column(
        confidence_enum,
        nullable=False,
        default=ConfidenceLevel.LOW,
        server_default=ConfidenceLevel.LOW.value,
    )
    working_memory_capacity: Mapped[int | None] = mapped_column(
        SmallInteger,
        nullable=True,
    )
    working_memory_capacity_confidence: Mapped[ConfidenceLevel] = mapped_column(
        confidence_enum,
        nullable=False,
        default=ConfidenceLevel.LOW,
        server_default=ConfidenceLevel.LOW.value,
    )
    attention_span: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    attention_span_confidence: Mapped[ConfidenceLevel] = mapped_column(
        confidence_enum,
        nullable=False,
        default=ConfidenceLevel.LOW,
        server_default=ConfidenceLevel.LOW.value,
    )
    performance_sensitivity: Mapped[int | None] = mapped_column(
        SmallInteger,
        nullable=True,
    )
    performance_sensitivity_confidence: Mapped[ConfidenceLevel] = mapped_column(
        confidence_enum,
        nullable=False,
        default=ConfidenceLevel.LOW,
        server_default=ConfidenceLevel.LOW.value,
    )


def dimension_checks() -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint(
            "cognitive_load_threshold IS NULL OR cognitive_load_threshold BETWEEN 1 AND 5",
            name="cognitive_load_threshold_range",
        ),
        CheckConstraint(
            "processing_speed IS NULL OR processing_speed BETWEEN 1 AND 5",
            name="processing_speed_range",
        ),
        CheckConstraint(
            "working_memory_capacity IS NULL OR working_memory_capacity BETWEEN 1 AND 5",
            name="working_memory_capacity_range",
        ),
        CheckConstraint(
            "attention_span IS NULL OR attention_span BETWEEN 1 AND 240",
            name="attention_span_range",
        ),
        CheckConstraint(
            "performance_sensitivity IS NULL OR performance_sensitivity BETWEEN 1 AND 5",
            name="performance_sensitivity_range",
        ),
    )


class LearnerProfile(LearnerProfileDimensionsMixin, Base):
    __tablename__ = "learner_profiles"
    __table_args__ = (
        *dimension_checks(),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(
            "observed_event_count >= 0",
            name="observed_event_count_nonnegative",
        ),
        UniqueConstraint("learner_id", name="uq_learner_profiles_learner_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    learner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(
        nullable=False,
        default=1,
        server_default="1",
    )
    observed_event_count: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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

    history: Mapped[list["LearnerProfileHistory"]] = relationship(
        back_populates="profile",
        order_by="LearnerProfileHistory.version",
        passive_deletes=True,
    )


class LearnerProfileHistory(LearnerProfileDimensionsMixin, Base):
    __tablename__ = "learner_profile_history"
    __table_args__ = (
        *dimension_checks(),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(
            "observed_event_count >= 0",
            name="observed_event_count_nonnegative",
        ),
        UniqueConstraint(
            "learner_profile_id",
            "version",
            name="uq_learner_profile_history_profile_version",
        ),
        Index(
            "ix_learner_profile_history_learner_created",
            "learner_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    learner_profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("learner_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    learner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(nullable=False)
    observed_event_count: Mapped[int] = mapped_column(nullable=False)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    change_source: Mapped[ProfileChangeSource] = mapped_column(
        change_source_enum,
        nullable=False,
    )
    changed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    change_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    profile: Mapped[LearnerProfile] = relationship(back_populates="history")
