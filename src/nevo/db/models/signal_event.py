import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base
from nevo.domain.signal_events.vocabulary import (
    LessonCompletionStatus,
    SignalEventType,
)

signal_event_type_enum = Enum(
    SignalEventType,
    name="signal_event_type",
    values_callable=lambda enum: [item.value for item in enum],
)
lesson_completion_status_enum = Enum(
    LessonCompletionStatus,
    name="lesson_completion_status",
    values_callable=lambda enum: [item.value for item in enum],
)


class LessonSession(Base):
    __tablename__ = "lesson_sessions"
    __table_args__ = (
        CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at",
            name="ended_at_after_started_at",
        ),
        CheckConstraint(
            "break_count >= 0 AND proactive_adjustments_count >= 0",
            name="counters_non_negative",
        ),
        Index(
            "ix_lesson_sessions_student_started_at",
            "student_id",
            "started_at",
        ),
        Index(
            "ix_lesson_sessions_lesson_started_at",
            "lesson_id",
            "started_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completion_status: Mapped[LessonCompletionStatus] = mapped_column(
        lesson_completion_status_enum,
        nullable=False,
        default=LessonCompletionStatus.IN_PROGRESS,
        server_default=LessonCompletionStatus.IN_PROGRESS.value,
    )
    exit_position: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )
    break_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    proactive_adjustments_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
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


class SignalEvent(Base):
    __tablename__ = "signal_events"
    __table_args__ = (
        Index(
            "ix_signal_events_student_session",
            "student_id",
            "session_id",
        ),
        Index(
            "ix_signal_events_student_timestamp",
            "student_id",
            "timestamp",
        ),
        Index(
            "ix_signal_events_type_timestamp",
            "event_type",
            "timestamp",
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
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
    )
    event_type: Mapped[SignalEventType] = mapped_column(
        signal_event_type_enum,
        nullable=False,
    )
    event_data: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
