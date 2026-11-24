"""Guardian consent for a /me learner under eighteen.

/me Phase 1b, ruling A (24 November 2026). The learner is registered, not
refused. They nominate their own guardian; the guardian consents from a link
without creating an account; the consent lands on the same consent_records
rows the school path writes, with confirmation_source 'guardian'.

Three states while consent is needed - outstanding, granted, dormant - and
dormancy changes only what the screen says, never what the learner can do:
resend and change of contact stay open throughout, and consent landing opens
upload immediately. Upload is the one gated action.

The dormancy clock starts at the learner's first nomination, or at
registration if they have not nominated anyone yet.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.consent.written import NOTICE_VERSION
from nevo.db.models.account import ConsentRecord, User
from nevo.db.models.consent import GuardianInvitation
from nevo.domain.accounts.age_bands import age_on
from nevo.domain.accounts.vocabulary import ConsentMethod, ConsentStatus, ConsentType
from nevo.domain.consent.vocabulary import ConsentConfirmationSource, ParentContactMethod

ADULT_AGE = 18
DORMANT_AFTER = timedelta(days=14)

#: What the guardian is asked, each as its own tick (the transfer outside
#: Nigeria is never folded into the first). Both are needed for a lesson to
#: be prepared, so both are needed for upload.
GUARDIAN_CONSENT_TYPES = (ConsentType.DATA_PROCESSING, ConsentType.CROSS_BORDER_TRANSFER)

#: The mail limiter for guardian links: one send per interval per learner,
#: and a daily ceiling, so the route cannot be used to post to an inbox.
SEND_INTERVAL = timedelta(minutes=2)
SENDS_PER_DAY = 5

ConsentStateName = Literal["not_required", "outstanding", "granted", "dormant"]


class GuardianConsentError(Exception):
    code = "guardian_consent_error"
    status_code = 409


class ConsentNotRequired(GuardianConsentError):
    code = "consent_not_required"


class ConsentAlreadyGranted(GuardianConsentError):
    code = "consent_already_granted"


class NoGuardianNominated(GuardianConsentError):
    code = "guardian_not_nominated"


class GuardianContactIsLearner(GuardianConsentError):
    code = "guardian_contact_is_learner"
    status_code = 422


class ConsentWithdrawn(GuardianConsentError):
    code = "consent_withdrawn"


class SendPaused(GuardianConsentError):
    code = "too_many_attempts"
    status_code = 429

    def __init__(self, retry_at: datetime) -> None:
        super().__init__(retry_at)
        self.retry_at = retry_at


@dataclass(frozen=True)
class ConsentView:
    required: bool
    state: ConsentStateName
    guardian_contact: str | None = None
    invited_at: datetime | None = None
    last_sent_at: datetime | None = None
    dormant_since: datetime | None = None
    blocked: tuple[str, ...] = ()
    actions: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class GuardianLinkView:
    learner_first_name: str | None
    state: Literal["awaiting", "consented", "replaced"]
    consent_types: tuple[str, ...]
    notice_version: str


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def is_minor(user: User, today=None) -> bool:
    age = age_on(user.date_of_birth, today)
    return age is not None and age < ADULT_AGE


async def _granted(session: AsyncSession, student_id: UUID) -> bool:
    confirmed = await session.scalar(
        select(func.count())
        .select_from(ConsentRecord)
        .where(
            ConsentRecord.subject_user_id == student_id,
            ConsentRecord.consent_type.in_(GUARDIAN_CONSENT_TYPES),
            ConsentRecord.status == ConsentStatus.CONFIRMED,
        )
    )
    return int(confirmed or 0) == len(GUARDIAN_CONSENT_TYPES)


async def _live_invitation(session: AsyncSession, student_id: UUID) -> GuardianInvitation | None:
    return await session.scalar(
        select(GuardianInvitation)
        .where(
            GuardianInvitation.student_id == student_id,
            GuardianInvitation.superseded_at.is_(None),
        )
        .order_by(GuardianInvitation.created_at.desc())
        .limit(1)
    )


async def consent_view(
    session: AsyncSession, user: User, now: datetime | None = None
) -> ConsentView:
    now = now or datetime.now(UTC)
    if not is_minor(user, now.date()):
        return ConsentView(required=False, state="not_required")
    if await _granted(session, user.id):
        return ConsentView(required=True, state="granted")

    live = await _live_invitation(session, user.id)
    first = await session.scalar(
        select(func.min(GuardianInvitation.created_at)).where(
            GuardianInvitation.student_id == user.id
        )
    )
    clock = first or user.created_at or now
    dormant = now - clock >= DORMANT_AFTER
    return ConsentView(
        required=True,
        state="dormant" if dormant else "outstanding",
        guardian_contact=live.contact if live else None,
        invited_at=live.created_at if live else None,
        last_sent_at=live.last_sent_at if live else None,
        dormant_since=clock + DORMANT_AFTER if dormant else None,
        blocked=("upload",),
        actions=("resend_invite", "change_contact") if live else ("invite_guardian",),
    )


async def upload_blocked_by_consent(session: AsyncSession, user: User) -> bool:
    """Phase 3's question: does consent, not allowance, stop this upload?"""

    view = await consent_view(session, user)
    return "upload" in view.blocked


async def _check_send_allowance(session: AsyncSession, student_id: UUID, now: datetime) -> None:
    row = (
        await session.execute(
            select(
                func.max(GuardianInvitation.last_sent_at),
                func.coalesce(func.sum(GuardianInvitation.send_count), 0),
                func.min(GuardianInvitation.last_sent_at),
            ).where(
                GuardianInvitation.student_id == student_id,
                GuardianInvitation.last_sent_at >= now - timedelta(days=1),
            )
        )
    ).one()
    latest, sends, oldest = row
    if latest is not None and latest + SEND_INTERVAL > now:
        raise SendPaused(latest + SEND_INTERVAL)
    if int(sends or 0) >= SENDS_PER_DAY and oldest is not None:
        raise SendPaused(oldest + timedelta(days=1))


async def _ready_for_invite(session: AsyncSession, user: User, now: datetime) -> None:
    if not is_minor(user, now.date()):
        raise ConsentNotRequired
    if await _granted(session, user.id):
        raise ConsentAlreadyGranted


async def nominate(
    session: AsyncSession, user: User, *, contact: str, now: datetime | None = None
) -> tuple[GuardianInvitation, str]:
    """Name a guardian, or change the one named. Returns the row and its token.

    The old row, if any, is superseded so its link stops working.
    """

    now = now or datetime.now(UTC)
    await _ready_for_invite(session, user, now)
    normal = contact.strip().casefold()
    if user.email and normal == user.email.casefold():
        raise GuardianContactIsLearner
    await _check_send_allowance(session, user.id, now)
    live = await _live_invitation(session, user.id)
    if live is not None:
        live.superseded_at = now
    token = secrets.token_urlsafe(32)
    invitation = GuardianInvitation(
        student_id=user.id,
        contact=normal,
        contact_method=ParentContactMethod.EMAIL,
        token_digest=digest(token),
        created_at=now,
        last_sent_at=now,
        send_count=1,
    )
    session.add(invitation)
    return invitation, token


async def resend(
    session: AsyncSession, user: User, now: datetime | None = None
) -> tuple[GuardianInvitation, str]:
    """Send the same nomination again with a fresh link; the old link stops."""

    now = now or datetime.now(UTC)
    await _ready_for_invite(session, user, now)
    live = await _live_invitation(session, user.id)
    if live is None:
        raise NoGuardianNominated
    await _check_send_allowance(session, user.id, now)
    token = secrets.token_urlsafe(32)
    live.token_digest = digest(token)
    live.last_sent_at = now
    live.send_count += 1
    return live, token


async def _by_token(session: AsyncSession, token: str) -> GuardianInvitation | None:
    return await session.scalar(
        select(GuardianInvitation).where(GuardianInvitation.token_digest == digest(token))
    )


async def link_view(session: AsyncSession, token: str) -> GuardianLinkView | None:
    invitation = await _by_token(session, token)
    if invitation is None:
        return None
    learner = await session.get(User, invitation.student_id)
    if invitation.consented_at is not None:
        state = "consented"
    elif invitation.superseded_at is not None:
        state = "replaced"
    else:
        state = "awaiting"
    return GuardianLinkView(
        learner_first_name=learner.first_name if learner else None,
        state=state,
        consent_types=tuple(item.value for item in GUARDIAN_CONSENT_TYPES),
        notice_version=NOTICE_VERSION,
    )


async def give_consent(
    session: AsyncSession,
    token: str,
    *,
    guardian_name: str,
    guardian_contact: str,
    relationship: str | None,
    now: datetime | None = None,
) -> Literal["consented", "already_consented", "replaced"] | None:
    """Record the guardian's consent on the learner's consent records.

    Returns None for a link that never existed. A replaced link records
    nothing: the learner changed who they named.
    """

    now = now or datetime.now(UTC)
    invitation = await _by_token(session, token)
    if invitation is None:
        return None
    if invitation.consented_at is not None:
        return "already_consented"
    if invitation.superseded_at is not None:
        return "replaced"

    existing = {
        record.consent_type: record
        for record in (
            await session.scalars(
                select(ConsentRecord).where(
                    ConsentRecord.subject_user_id == invitation.student_id,
                    ConsentRecord.consent_type.in_(GUARDIAN_CONSENT_TYPES),
                )
            )
        ).all()
    }
    if any(record.status is ConsentStatus.WITHDRAWN for record in existing.values()):
        # The school path never overrules a withdrawal from a confirm route;
        # neither does this one.
        raise ConsentWithdrawn

    for consent_type in GUARDIAN_CONSENT_TYPES:
        record = existing.get(consent_type)
        if record is None:
            record = ConsentRecord(subject_user_id=invitation.student_id, consent_type=consent_type)
            session.add(record)
        record.status = ConsentStatus.CONFIRMED
        record.confirmation_source = ConsentConfirmationSource.GUARDIAN
        record.confirmed_by_admin_id = None
        record.confirmed_by_parent_id = None
        record.confirmed_via = ConsentMethod.DIGITAL
        record.confirmed_at = now
        record.last_changed_at = now
        record.last_channel = "guardian_link"
        record.parent_name_on_form = guardian_name
        record.parent_relationship = relationship
        record.notice_version = NOTICE_VERSION

    invitation.consented_at = now
    invitation.guardian_name = guardian_name
    invitation.guardian_contact = guardian_contact.strip().casefold()
    invitation.guardian_relationship = relationship
    return "consented"
