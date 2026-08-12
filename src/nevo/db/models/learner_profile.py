import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
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
    EngagementAnomalyScope,
    EngagementAnomalyType,
    GamingSuspicionLevel,
    ProcessingChannelPreference,
    ProfileAttentionFlagStatus,
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
attention_flag_status_enum = Enum(
    ProfileAttentionFlagStatus,
    name="profile_attention_flag_status",
    values_callable=lambda enum: [item.value for item in enum],
)
gaming_suspicion_level_enum = Enum(
    GamingSuspicionLevel,
    name="gaming_suspicion_level",
    values_callable=lambda enum: [item.value for item in enum],
)
engagement_anomaly_type_enum = Enum(
    EngagementAnomalyType,
    name="engagement_anomaly_type",
    values_callable=lambda enum: [item.value for item in enum],
)
engagement_anomaly_scope_enum = Enum(
    EngagementAnomalyScope,
    name="engagement_anomaly_scope",
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
        CheckConstraint(
            "gaming_anomaly_count >= 0",
            name="gaming_anomaly_count_nonnegative",
        ),
        CheckConstraint(
            "(gaming_suspicion_level = 'none') = (gaming_suspicion_updated_at IS NULL)",
            name="gaming_suspicion_level_matches_timestamp",
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
    # SCRUM-62. Stored only: no runtime path reads or writes these yet, and
    # they are never returned on a learner-facing or parent-facing contract.
    # Deliberately not on LearnerProfileDimensionsMixin: this is not a
    # learning dimension and must not join the inference dimension set.
    gaming_suspicion_level: Mapped[GamingSuspicionLevel] = mapped_column(
        gaming_suspicion_level_enum,
        nullable=False,
        default=GamingSuspicionLevel.NONE,
        server_default=GamingSuspicionLevel.NONE.value,
    )
    gaming_suspicion_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    gaming_anomaly_count: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
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


class LearnerProfileAttentionFlag(Base):
    __tablename__ = "learner_profile_attention_flags"
    __table_args__ = (
        Index(
            "ix_learner_profile_attention_flags_student_created",
            "student_id",
            "created_at",
        ),
        Index(
            "ix_learner_profile_attention_flags_status_created",
            "status",
            "created_at",
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
    lesson_session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("lesson_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    learner_profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("learner_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    dimension: Mapped[str] = mapped_column(String(120), nullable=False)
    current_value: Mapped[str | None] = mapped_column(String(120), nullable=True)
    recommended_value: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )
    rationale: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[ProfileAttentionFlagStatus] = mapped_column(
        attention_flag_status_enum,
        nullable=False,
        default=ProfileAttentionFlagStatus.OPEN,
        server_default=ProfileAttentionFlagStatus.OPEN.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class LearnerEngagementAnomaly(Base):
    """One recorded deviation from a learner's own prior baseline (SCRUM-62).

    An append-only ledger. Rows are evidence, not verdicts: the summarised
    judgement lives on ``learner_profiles.gaming_suspicion_level``. Nothing
    writes here yet. ``rule_key`` names the
    ``nevo.domain.learner_profiles.gaming_rules`` rule that produced the row,
    so thresholds can be revised without orphaning history.
    """

    __tablename__ = "learner_engagement_anomalies"
    __table_args__ = (
        CheckConstraint(
            "baseline_value >= 0 AND observed_value >= 0",
            name="anomaly_values_nonnegative",
        ),
        CheckConstraint(
            "deviation_ratio > 0",
            name="deviation_ratio_positive",
        ),
        CheckConstraint(
            "distinct_content_types >= 1 AND observation_count >= 1",
            name="anomaly_counts_positive",
        ),
        Index(
            "ix_learner_engagement_anomalies_student_detected",
            "student_id",
            "detected_at",
        ),
        Index(
            "ix_learner_engagement_anomalies_rule_detected",
            "rule_key",
            "detected_at",
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
    learner_profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("learner_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    lesson_session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("lesson_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    anomaly_type: Mapped[EngagementAnomalyType] = mapped_column(
        engagement_anomaly_type_enum,
        nullable=False,
    )
    scope: Mapped[EngagementAnomalyScope] = mapped_column(
        engagement_anomaly_scope_enum,
        nullable=False,
    )
    rule_key: Mapped[str] = mapped_column(String(120), nullable=False)
    # Baseline is always the learner's own prior norm, never a cohort average.
    baseline_value: Mapped[float] = mapped_column(Float, nullable=False)
    observed_value: Mapped[float] = mapped_column(Float, nullable=False)
    deviation_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    observation_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    distinct_content_types: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
