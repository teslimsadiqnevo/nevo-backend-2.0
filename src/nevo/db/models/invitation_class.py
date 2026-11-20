"""The classes and subjects an invited teacher is to hold on acceptance."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base


class SchoolInvitationClass(Base):
    """One class, with one subject, that an invited teacher will teach.

    An invitation used to carry a single ``class_id`` and nothing else, which
    meant a subject teacher covering six classes had to be invited six times
    on the first day of setup - the same person, six emails, six passwords to
    set. Lydia approved several classes per invitation on 20 November.

    A row per class *and subject* rather than a list of classes, because one
    teacher can take two subjects to the same class and the pair is what an
    assignment is keyed on. SCRUM-194 means a teacher cannot be assigned
    without a subject, so the subject here is NOT NULL: an invitation that
    cannot be applied is worse than one that was refused when it was written.

    Nothing is applied until acceptance, and then all of it in one
    transaction. A part-applied acceptance would leave a teacher holding some
    of their classes and not others, which looks accepted and is not - the
    failure Lydia's ask names, and the reason this is a table rather than
    something assembled per class as the invitation is accepted.

    T15, 20 November.
    """

    __tablename__ = "school_invitation_classes"
    __table_args__ = (
        #: One row per class and subject. Inviting somebody twice to the same
        #: pair is a duplicate, not two assignments.
        UniqueConstraint(
            "invitation_id",
            "class_id",
            "school_subject_id",
            name="uq_invitation_class_subject",
        ),
        Index("ix_school_invitation_classes_invitation", "invitation_id"),
        Index("ix_school_invitation_classes_class", "class_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    invitation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("school_invitations.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Cascade: a class deleted before the invitation is accepted takes this
    #: row with it, which is correct - there is nothing left to attach to -
    #: and acceptance then simply attaches the classes that remain.
    class_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("classes.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Required. SCRUM-194: a teacher cannot be assigned without a subject,
    #: so an invitation that named a class and no subject could never be
    #: applied.
    school_subject_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("school_subjects.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
