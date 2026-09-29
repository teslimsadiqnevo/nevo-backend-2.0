"""Two records the agreement asks for that the product never kept.

A date of birth decides whether a child is old enough to be offered the
product at all, and it came from one place - the school's roster - with
nothing to check it against. It is now asked of the parent too and the two
are compared.

And a parent who never answered was asked again indefinitely, because nothing
recorded that they had been asked and had not replied. A refusal outlives the
learner's roster data on purpose: it is what stops the school inviting the
same parent for the same child a second time.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base
from nevo.domain.consent.vocabulary import AgeCheckState, ConsentRefusalReason

age_check_state_enum = Enum(
    AgeCheckState,
    name="age_check_state",
    values_callable=lambda enum: [item.value for item in enum],
)
consent_refusal_reason_enum = Enum(
    ConsentRefusalReason,
    name="consent_refusal_reason",
    values_callable=lambda enum: [item.value for item in enum],
)


class AgeCheck(Base):
    """The school's date of birth beside the parent's, and what came of it."""

    __tablename__ = "age_checks"
    __table_args__ = (
        Index("ix_age_checks_student", "student_id", unique=True),
        Index(
            "ix_age_checks_school_state",
            "school_id",
            "state",
            postgresql_where=text("state = 'mismatch'"),
        ),
        CheckConstraint(
            "(state = 'resolved') = (resolved_at IS NOT NULL AND resolved_by_user_id IS NOT NULL)",
            name="age_check_resolution_matches_state",
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
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: What the school uploaded. Kept as it was at the time of the check, so a
    #: later correction does not erase what the disagreement was about.
    school_date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: What the parent confirmed on the consent screen.
    parent_date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    state: Mapped[AgeCheckState] = mapped_column(
        age_check_state_enum,
        nullable=False,
        default=AgeCheckState.AWAITING_PARENT,
        server_default=AgeCheckState.AWAITING_PARENT.value,
    )
    #: The date both sides settled on, written back to the roster when it is
    #: resolved.
    agreed_date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: How it was settled, in the words of whoever settled it. A mismatch is
    #: an exception a person closes, not a rule the software applies.
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
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

    @property
    def blocks_access(self) -> bool:
        """A disagreement nobody has settled keeps the child out."""

        return self.state is AgeCheckState.MISMATCH


class ConsentRefusal(Base):
    """A parent who was asked and is not to be asked again.

    Deliberately minimal, because it outlives the learner's roster data: the
    child's id, a fingerprint of the address rather than the address, and the
    reason. It cannot be read back into a contact list, which is the point -
    it exists to prevent contact, not to enable it.
    """

    __tablename__ = "consent_refusals"
    __table_args__ = (
        Index(
            "ix_consent_refusals_student_contact",
            "student_id",
            "contact_digest",
            unique=True,
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
    #: Kept as a plain id rather than a foreign key: the learner row is
    #: deleted thirty days after this is written, and a refusal that vanishes
    #: with it would let the school ask again the next morning.
    student_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    #: SHA-256 of the lowercased address. Enough to recognise the same parent
    #: being invited again, useless for reaching them.
    contact_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[ConsentRefusalReason] = mapped_column(
        consent_refusal_reason_enum,
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    #: When the learner's roster data was removed. Null until the sweep runs.
    roster_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
