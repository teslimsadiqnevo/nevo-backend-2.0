import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
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
from nevo.domain.intelligence.vocabulary import (
    ContentModality,
    ContentParseStatus,
    KeyPointConfidence,
    KeyPointReviewState,
    LessonContentType,
    LessonSourceType,
)

lesson_source_type_enum = Enum(
    LessonSourceType,
    name="lesson_source_type",
    values_callable=lambda enum: [item.value for item in enum],
)
content_parse_status_enum = Enum(
    ContentParseStatus,
    name="content_parse_status",
    values_callable=lambda enum: [item.value for item in enum],
)
key_point_confidence_enum = Enum(
    KeyPointConfidence,
    name="key_point_confidence",
    values_callable=lambda enum: [item.value for item in enum],
)
key_point_review_state_enum = Enum(
    KeyPointReviewState,
    name="key_point_review_state",
    values_callable=lambda enum: [item.value for item in enum],
)
lesson_content_type_enum = Enum(
    LessonContentType,
    name="lesson_content_type",
    values_callable=lambda enum: [item.value for item in enum],
)


class Lesson(Base):
    __tablename__ = "lessons"
    __table_args__ = (
        CheckConstraint(
            "segment_count >= 0 AND review_segment_count >= 0",
            name="lesson_segment_counts_non_negative",
        ),
        Index("ix_lessons_school_created_at", "school_id", "created_at"),
        Index("ix_lessons_created_by_created_at", "created_by_user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    school_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("schools.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_type: Mapped[LessonSourceType] = mapped_column(
        lesson_source_type_enum,
        nullable=False,
    )
    source_reference: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    parser_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    status: Mapped[ContentParseStatus] = mapped_column(
        content_parse_status_enum,
        nullable=False,
        default=ContentParseStatus.PENDING,
        server_default=ContentParseStatus.PENDING.value,
    )
    segment_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    review_segment_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    #: Sum of the lesson's segment estimates, denormalised so a list view can
    #: show a duration without loading every segment.
    estimated_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    confirmation_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Written for the child, not the teacher. confirmation_summary is the
    #: parser talking about its own confidence; this is what a learner reads
    #: when the lesson ends.
    recap: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Why this lesson could not be prepared, in words a teacher can read.
    #: Denormalised from the parse run that failed, because the library list
    #: has the lesson and not the run - and a card that says "couldn't be
    #: processed" with no reason is a read per row to render one sentence.
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: What a teacher quotes for it, carried the same way and for the same
    #: reason.
    incident_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: Questions to close on, in the same shape as a segment checkpoint so one
    #: renderer serves both.
    assessment: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
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


class ContentParseRun(Base):
    __tablename__ = "content_parse_runs"
    __table_args__ = (
        CheckConstraint(
            "chunk_count >= 1 AND gemini_call_count >= 0 "
            "AND calculation_segment_count >= 0 AND tts_call_count >= 0",
            name="content_parse_run_counts_non_negative",
        ),
        Index("ix_content_parse_runs_lesson_created_at", "lesson_id", "created_at"),
        Index("ix_content_parse_runs_status_created_at", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("lessons.id", ondelete="CASCADE"),
        nullable=False,
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[ContentParseStatus] = mapped_column(
        content_parse_status_enum,
        nullable=False,
        default=ContentParseStatus.PROCESSING,
        server_default=ContentParseStatus.PROCESSING.value,
    )
    source_type: Mapped[LessonSourceType] = mapped_column(
        lesson_source_type_enum,
        nullable=False,
    )
    source_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    chunk_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    gemini_call_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    calculation_segment_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    tts_call_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    review_notes: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    #: Raw, for us. Whatever the driver or the provider said; never prose and
    #: never to be shown to a teacher.
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The sentence a teacher reads. ``failure_reason`` on the wire used to be
    #: the column above, so a name promising prose delivered a stack trace.
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: What a teacher quotes, and what finds it in the log.
    incident_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class LessonSegment(Base):
    __tablename__ = "lesson_segments"
    __table_args__ = (
        CheckConstraint("sequence_order >= 1", name="sequence_order_positive"),
        CheckConstraint(
            "jsonb_array_length(available_modalities) >= 1",
            name="available_modalities_not_empty",
        ),
        Index(
            "ix_lesson_segments_lesson_sequence_order",
            "lesson_id",
            "sequence_order",
            unique=True,
        ),
        Index("ix_lesson_segments_lesson_content_type", "lesson_id", "content_type"),
        Index(
            "ix_lesson_segments_needs_review",
            "lesson_id",
            "needs_review",
            postgresql_where=text("needs_review = true"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("lessons.id", ondelete="CASCADE"),
        nullable=False,
    )
    parse_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("content_parse_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    segment_key: Mapped[str] = mapped_column(String(120), nullable=False)
    content_type: Mapped[LessonContentType] = mapped_column(
        lesson_content_type_enum,
        nullable=False,
    )
    sequence_order: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    available_modalities: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
    )
    comprehension_checkpoints: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    text_variant: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    visual_variant: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    audio_variant: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    interactive_variant: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    calculation_variant: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    #: ``{"simplified": {"body": ...}, "expanded": {"body": ...}}``, keyed by
    #: the adaptation engine's own action names. Null where nothing was
    #: written: the engine falls back to ``body``, which is the teacher's own
    #: text and always present.
    depth_variants: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    estimated_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    needs_review: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    #: When a teacher approved this segment's variants for children to see,
    #: and who did. Null means nobody has, and the lesson cannot be assigned.
    #: Segments that predate the gate carry a timestamp and no approver,
    #: because nobody did approve them and saying a teacher had would be a
    #: false record on a screen that shows the name.
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    review_reasons: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
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


class LessonKeyPoint(Base):
    """One key point drawn from a segment, and where a teacher left it.

    Key points also live inside a segment's ``text_variant`` for rendering.
    They are rows as well because a review is per point: a teacher accepts,
    rewrites or removes one at a time, and a row is the only place that
    decision, its author and its time can live. The variant stays the thing a
    child reads; this is the thing a teacher works through.
    """

    __tablename__ = "lesson_key_points"
    __table_args__ = (
        CheckConstraint("position >= 0", name="lesson_key_point_position_non_negative"),
        CheckConstraint(
            "(review_state IN ('settled', 'unsure')"
            " AND resolved_at IS NULL AND resolved_by IS NULL)"
            " OR (review_state IN ('accepted', 'amended', 'removed')"
            " AND resolved_at IS NOT NULL)",
            name="lesson_key_point_resolution_matches_state",
        ),
        Index(
            "ix_lesson_key_points_lesson_position",
            "lesson_id",
            "segment_id",
            "position",
            unique=True,
        ),
        Index(
            "ix_lesson_key_points_outstanding",
            "lesson_id",
            postgresql_where=text("review_state = 'unsure'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("lessons.id", ondelete="CASCADE"),
        nullable=False,
    )
    segment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("lesson_segments.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Where it sits among that segment's key points.
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    #: What Nevo extracted, kept as extracted even after a teacher rewrites it,
    #: so the screen can show what it read next to what the teacher made of it.
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    #: The teacher's wording, once they have written one.
    amended_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The segment text this was drawn from. Stored rather than looked up, so
    #: a later edit to the segment cannot silently rewrite the evidence a
    #: teacher was shown.
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[KeyPointConfidence] = mapped_column(
        key_point_confidence_enum,
        nullable=False,
    )
    review_state: Mapped[KeyPointReviewState] = mapped_column(
        key_point_review_state_enum,
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
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

    @property
    def text(self) -> str:
        """What the lesson says now: the teacher's wording if they wrote one."""

        return self.amended_text or self.extracted_text


def modality_values(modalities: list[ContentModality]) -> list[str]:
    return [modality.value for modality in modalities]
