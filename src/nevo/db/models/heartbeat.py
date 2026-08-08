import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, UniqueConstraint, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base


class SystemHeartbeat(Base):
    __tablename__ = "system_heartbeats"
    __table_args__ = (
        UniqueConstraint("beat_date", name="uq_system_heartbeats_beat_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    beat_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
