import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base
from nevo.domain.signal_events.vocabulary import SignalEventType

signal_event_type_enum = Enum(
    SignalEventType,
    name="signal_event_type",
    values_callable=lambda enum: [item.value for item in enum],
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

