"""What a school has uploaded, before any of it is real.

A school could create classes, add teachers and add students without paying
anything: the product was fully usable before money changed hands. The order
is now upload, derive, confirm, pay, activate, and nothing an upload proposes
touches a person until the last step.

Uploaded rows therefore cannot be people yet. They sit here, uncommitted and
editable, and the confirmation screen is what protects a school from a typo
becoming a phantom class - better than rejecting the row, because the school
sees the whole derived list and corrects it before anything exists.
"""

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
from nevo.domain.onboarding.vocabulary import OnboardingRowKind, OnboardingStage

onboarding_stage_enum = Enum(
    OnboardingStage,
    name="onboarding_stage",
    values_callable=lambda enum: [item.value for item in enum],
)
onboarding_row_kind_enum = Enum(
    OnboardingRowKind,
    name="onboarding_row_kind",
    values_callable=lambda enum: [item.value for item in enum],
)


class SchoolOnboarding(Base):
    """One school's journey from an uploaded file to an open workspace."""

    __tablename__ = "school_onboardings"
    __table_args__ = (
        Index("ix_school_onboardings_school", "school_id", unique=True),
        CheckConstraint(
            "(stage = 'activated') = (activated_at IS NOT NULL)",
            name="onboarding_activation_matches_stage",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
    )
    stage: Mapped[OnboardingStage] = mapped_column(
        onboarding_stage_enum,
        nullable=False,
        default=OnboardingStage.UPLOADING,
        server_default=OnboardingStage.UPLOADING.value,
    )
    #: The invoice the school has to settle before anybody hears from Nevo.
    #: Null until the headcount is confirmed and priced.
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("invoices.id", ondelete="SET NULL"),
        nullable=True,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    #: When accounts were created, invitations sent, consent requested and
    #: credentials released. Never set before the invoice is paid.
    activated_at: Mapped[datetime | None] = mapped_column(
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


class OnboardingRow(Base):
    """One line of an uploaded file, as read and as corrected.

    The row keeps its number and the values it arrived with, because a school
    uploading four hundred children will not notice thirty going missing: a
    rejection has to be able to say which line, which field and what was in
    it. Corrections are kept beside the original rather than over it, so the
    screen can always show what the file actually said.
    """

    __tablename__ = "onboarding_rows"
    __table_args__ = (
        CheckConstraint("row_number >= 1", name="onboarding_row_number_positive"),
        CheckConstraint(
            "(rejected = false) OR (rejection_reason IS NOT NULL)",
            name="onboarding_rejection_has_a_reason",
        ),
        Index("ix_onboarding_rows_onboarding_kind", "onboarding_id", "kind", "row_number"),
        Index("ix_onboarding_rows_class", "onboarding_id", "normalised_class_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    onboarding_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("school_onboardings.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[OnboardingRowKind] = mapped_column(onboarding_row_kind_enum, nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    #: The row as uploaded, keyed by the column names the template asks for.
    values: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    class_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    normalised_class_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rejected: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    rejection_field: Mapped[str | None] = mapped_column(String(80), nullable=True)
    rejection_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Shown to the school verbatim, so it says what to do rather than naming
    #: an internal state, which is how an import failure read before.
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Cleared by a school taking a row out on the confirmation screen.
    excluded: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    @property
    def countable(self) -> bool:
        """Whether this row is a person the school is asking Nevo to carry."""

        return not self.rejected and not self.excluded
