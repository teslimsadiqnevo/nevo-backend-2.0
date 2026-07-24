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
    confirmation_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    needs_review: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
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


def modality_values(modalities: list[ContentModality]) -> list[str]:
    return [modality.value for modality in modalities]
