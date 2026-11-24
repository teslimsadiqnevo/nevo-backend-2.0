"""/me tables: a learner's purchased months (Phase 4)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base


class MePurchase(Base):
    """One checkout a /me learner started, and the month it bought if paid.

    Holds nothing about the instrument used to pay: no card, no authorization
    code, no customer code. That is the rule, and tests/
    test_nevo_stores_no_payment_token.py holds this table to it.
    """

    __tablename__ = "me_purchases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'success', 'failed', 'abandoned')", name="status_known"
        ),
        CheckConstraint(
            "(status = 'success') = (period_start IS NOT NULL AND period_end IS NOT NULL)",
            name="a_paid_month_has_a_period",
        ),
        Index("ix_me_purchases_learner_period", "learner_id", "period_end"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    learner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    tier_key: Mapped[str] = mapped_column(String(20), nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reference: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    provider_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
