"""A parent who never answered, and what happens to the child's data.

The agreement's rule: if a parent does not confirm within thirty days, the
learner is not activated, and their roster data goes within thirty days after
that. What survives is a minimal record that this parent was asked and did not
answer, so the school does not invite them again next term and start the same
thirty days over.

Two sweeps rather than one, on purpose. A school whose consent emails went to
spam has thirty days to notice and resend before anything is deleted, and the
deletion is a separate decision from the expiry that preceded it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.account import ConsentRecord, StudentClassEnrollment, User
from nevo.db.models.consent import ConsentInvitation, ParentLink
from nevo.db.models.consent_assurance import ConsentRefusal
from nevo.domain.accounts.vocabulary import ConsentStatus, UserStatus
from nevo.domain.consent.vocabulary import ConsentRefusalReason
from nevo.retention.anonymisation import anonymise_student

#: How long after the invitation expires the learner's roster data is removed.
#: The agreement says within thirty days of the expiry; this runs at the end
#: of that window rather than the start, because a school that notices on day
#: twenty-nine should still find its pupil there to resend to.
DELETE_ROSTER_AFTER = timedelta(days=30)


def contact_digest(contact: str) -> str:
    """A fingerprint of an address, not the address.

    The refusal outlives the learner's row, so it must not be readable back
    into a contact list. This is enough to recognise the same parent being
    invited for the same child again and useless for reaching them.
    """

    return hashlib.sha256(contact.strip().casefold().encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ConsentExpirySweep:
    expired: int
    rosters_removed: int

    def summary(self) -> str:
        return (
            f"recorded {self.expired} unanswered consent requests, "
            f"removed {self.rosters_removed} expired roster entries"
        )


class ConsentExpiryService:
    """Closes out consent requests nobody answered."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def sweep(self, *, now: datetime | None = None) -> ConsentExpirySweep:
        current = now or datetime.now(UTC)
        expired = await self._record_unanswered(current)
        removed = await self._remove_expired_rosters(current)
        return ConsentExpirySweep(expired=expired, rosters_removed=removed)

    async def _record_unanswered(self, now: datetime) -> int:
        """Write down that this parent was asked and did not answer.

        Nothing is deleted here. The learner simply never activated, which is
        already true - the gate has been refusing them since the day the
        school uploaded them.
        """

        recorded = 0
        async with self._sessions.begin() as session:
            rows = await session.execute(
                select(ConsentInvitation, ParentLink)
                .join(ParentLink, ParentLink.id == ConsentInvitation.parent_link_id)
                .where(
                    ConsentInvitation.accepted_at.is_(None),
                    ConsentInvitation.revoked_at.is_(None),
                    ConsentInvitation.expires_at <= now,
                )
            )
            for invitation, link in rows.all():
                digest = contact_digest(link.parent_contact)
                already = await session.scalar(
                    select(ConsentRefusal.id).where(
                        ConsentRefusal.student_id == invitation.student_id,
                        ConsentRefusal.contact_digest == digest,
                    )
                )
                if already is not None:
                    continue
                session.add(
                    ConsentRefusal(
                        school_id=invitation.school_id,
                        student_id=invitation.student_id,
                        contact_digest=digest,
                        reason=ConsentRefusalReason.NO_RESPONSE,
                        recorded_at=now,
                    )
                )
                recorded += 1
        return recorded

    async def _remove_expired_rosters(self, now: datetime) -> int:
        """Remove the learner's roster data, thirty days after the expiry.

        The child never used Nevo - the gate saw to that - so there is no
        learning record to keep. What goes is the roster entry the school
        uploaded: the name, the class, the parent's contact details and the
        consent rows. What stays is the refusal, without which the school
        would upload the same child next week and start again.
        """

        cutoff = now - DELETE_ROSTER_AFTER
        removed = 0
        async with self._sessions.begin() as session:
            refusals = list(
                await session.scalars(
                    select(ConsentRefusal).where(
                        ConsentRefusal.reason == ConsentRefusalReason.NO_RESPONSE,
                        ConsentRefusal.roster_deleted_at.is_(None),
                        ConsentRefusal.recorded_at <= cutoff,
                    )
                )
            )
            for refusal in refusals:
                if await self._consent_arrived_late(session, refusal.student_id):
                    # A parent who answered after the link expired is a parent
                    # who answered. Nothing is deleted, and the refusal goes.
                    await session.delete(refusal)
                    continue
                await self._remove_roster_entry(session, refusal.student_id, now)
                refusal.roster_deleted_at = now
                removed += 1
        return removed

    @staticmethod
    async def _consent_arrived_late(session: AsyncSession, student_id: UUID) -> bool:
        status = await session.scalar(
            select(ConsentRecord.status).where(
                ConsentRecord.subject_user_id == student_id,
                ConsentRecord.status == ConsentStatus.CONFIRMED,
            )
        )
        return status is not None

    @staticmethod
    async def _remove_roster_entry(
        session: AsyncSession,
        student_id: UUID,
        now: datetime,
    ) -> None:
        student = await session.get(User, student_id)
        if student is None:
            return
        await session.execute(
            delete(StudentClassEnrollment).where(StudentClassEnrollment.student_id == student_id)
        )
        await session.execute(delete(ParentLink).where(ParentLink.student_id == student_id))
        await session.execute(
            delete(ConsentRecord).where(ConsentRecord.subject_user_id == student_id)
        )
        # Anonymised rather than deleted outright: the row is referenced by
        # tables that refuse to lose it, and the same function the retention
        # sweep uses leaves nothing on it that identifies a person.
        anonymise_student(student, now=now)
        student.date_of_birth = None
        student.status = UserStatus.DEACTIVATED


async def already_refused(
    session: AsyncSession,
    *,
    student_id: UUID,
    parent_contact: str,
) -> bool:
    """Whether this parent has already been asked about this child and said no.

    Checked before a school sends another invitation, because "we do not
    contact them again" has to be enforced where the contact happens.
    """

    refusal = await session.scalar(
        select(ConsentRefusal.id).where(
            ConsentRefusal.student_id == student_id,
            ConsentRefusal.contact_digest == contact_digest(parent_contact),
        )
    )
    return refusal is not None
