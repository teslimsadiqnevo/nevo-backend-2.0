"""A parent withdraws from inside their account, not from an expiring link.

Withdrawal has to be no harder than giving consent. It was harder: the only
route was the link in the original email, which stopped working after the
invitation expired, and a parent signed into their own dashboard had no way
to do it at all. So a parent who consented in September and changed their
mind in November had no route, which is the opposite of what was promised.

These endpoints are the parent's own. They need no token, only their session,
and they cover the three rights the agreement names: withdraw, object, and
ask for the data held.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.api.casing import CAMEL_CONFIG
from nevo.api.dependencies import DatabaseSession
from nevo.api.parents import ParentDependency
from nevo.api.response_models import CamelResponse
from nevo.consent.expiry import contact_digest
from nevo.db.models.account import ConsentRecord, User
from nevo.db.models.consent import ParentLink
from nevo.db.models.consent_assurance import ConsentRefusal
from nevo.db.models.product import ParentDataRequest
from nevo.domain.accounts.vocabulary import (
    ConsentMethod,
    ConsentStatus,
    ConsentType,
    UserStatus,
)
from nevo.domain.consent.vocabulary import (
    REQUIRED_LEARNING_CONSENT,
    ConsentConfirmationSource,
    ConsentRefusalReason,
    ParentRightType,
)

router = APIRouter(prefix="/api/v1/parents/me", tags=["consent"])


class ConsentHeld(CamelResponse):
    """One consent, in the parent's own terms."""

    consent_type: ConsentType
    status: ConsentStatus
    decided_at: datetime | None
    #: True when withdrawing this one stops their child using Nevo. Said
    #: plainly, so a parent is never surprised by what a button does.
    stops_access: bool
    can_withdraw: bool


class ChildConsents(CamelResponse):
    student_id: UUID
    student_first_name: str | None
    consents: list[ConsentHeld]


class WithdrawalRequest(BaseModel):
    model_config = CAMEL_CONFIG

    student_id: Annotated[UUID, Field(alias="studentId")]
    #: Which consents to withdraw. Omitted means all of them, which is what a
    #: parent pressing "withdraw my consent" means.
    consent_types: Annotated[
        list[ConsentType] | None,
        Field(default=None, alias="consentTypes"),
    ] = None
    reason: Annotated[str | None, Field(default=None, max_length=1000)] = None


class RestoreRequest(BaseModel):
    """Which consents a parent is giving back.

    The same shape as a withdrawal and deliberately its own model: a client
    generated off a route whose body is called WithdrawalRequest reads as
    though it withdraws.
    """

    model_config = CAMEL_CONFIG

    student_id: Annotated[UUID, Field(alias="studentId")]
    #: Omitted means every consent this parent withdrew, which is what a
    #: parent pressing "give permission again" means.
    consent_types: Annotated[
        list[ConsentType] | None,
        Field(default=None, alias="consentTypes"),
    ] = None
    reason: Annotated[str | None, Field(default=None, max_length=1000)] = None


class RightRequest(BaseModel):
    model_config = CAMEL_CONFIG

    student_id: Annotated[UUID, Field(alias="studentId")]
    reason: Annotated[str | None, Field(default=None, max_length=1000)] = None


class RightOutcome(CamelResponse):
    request_id: UUID
    request_type: ParentRightType
    student_id: UUID
    #: What changed as a result, in words the parent can check against what
    #: they were told would happen.
    effect: str
    withdrawn_types: list[ConsentType] = Field(default_factory=list)
    #: Consents given back, for the restore route. Kept separate from
    #: withdrawn_types rather than reusing it: a client reading
    #: "withdrawnTypes" off a restore would report the opposite of what
    #: happened to the parent who just did it.
    restored_types: list[ConsentType] = Field(default_factory=list)
    recorded_at: datetime


async def _own_child(session: AsyncSession, parent_id: UUID, student_id: UUID) -> User:
    """The child this parent is actually linked to, and nobody else's."""

    link = await session.scalar(
        select(ParentLink).where(
            ParentLink.parent_id == parent_id,
            ParentLink.student_id == student_id,
        )
    )
    student = await session.get(User, student_id) if link else None
    if link is None or student is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "child_not_linked", "message": "That is not your child's record."},
        )
    return student


async def _can_withdraw(
    session: AsyncSession, student_id: UUID, parent_id: UUID, record: ConsentRecord,
) -> bool:
    if record.confirmed_by_parent_id is not None:
        return record.confirmed_by_parent_id == parent_id
    if record.consent_holder_parent_link_id is not None:
        holder = await session.get(ParentLink, record.consent_holder_parent_link_id)
        return holder is not None and holder.student_id == student_id and holder.parent_id == parent_id
    # A school-recorded written consent has no parent account as its actor.
    # SCRUM-306: the adult who can withdraw it is the adult whose name is on
    # the paper form. The roster does not capture which adult signed, so the
    # first guardian linked to the child stands in until it does.
    #
    # Ordered over every link, not only the ones with an account. Filtering
    # to parent_id IS NOT NULL meant an adult linked first who never
    # registered was skipped, so a second guardian who happened to register
    # first became the first link and could withdraw a consent they were
    # never asked for.
    first_link = await session.scalar(
        select(ParentLink.parent_id)
        .where(ParentLink.student_id == student_id)
        .order_by(ParentLink.created_at, ParentLink.id)
        .limit(1)
    )
    return first_link is not None and first_link == parent_id


@router.get("/consents", response_model=list[ChildConsents])
async def my_consents(
    parent_id: ParentDependency,
    session: DatabaseSession,
) -> list[ChildConsents]:
    """What this parent has agreed to, per child.

    A parent cannot withdraw what they cannot see, so the list comes first.
    """

    links = list(await session.scalars(select(ParentLink).where(ParentLink.parent_id == parent_id)))
    out: list[ChildConsents] = []
    for link in links:
        student = await session.get(User, link.student_id)
        records = list(
            await session.scalars(
                select(ConsentRecord)
                .where(ConsentRecord.subject_user_id == link.student_id)
                .order_by(ConsentRecord.consent_type)
            )
        )
        out.append(
            ChildConsents(
                student_id=link.student_id,
                student_first_name=student.first_name if student else None,
                consents=[
                    ConsentHeld(
                        consent_type=record.consent_type,
                        status=record.status,
                        decided_at=record.confirmed_at or record.last_changed_at,
                        stops_access=record.consent_type is REQUIRED_LEARNING_CONSENT,
                        can_withdraw=await _can_withdraw(
                            session, link.student_id, parent_id, record
                        ),
                    )
                    for record in records
                ],
            )
        )
    return out


def _refuse_another_parents_consent(
    records: list[ConsentRecord],
    *,
    wanted: set[ConsentType],
    parent_id: UUID,
) -> None:
    """A guardian withdraws the consent they gave, and nobody else's.

    Any link to a child used to carry the right to withdraw, so a second
    guardian added after consent was given could suspend a child on the
    strength of a consent the first guardian had given. Ruling from Lydia,
    5 November: adding a guardian must not be able to withdraw the child.

    Where no parent gave the consent - the school recorded it from a paper
    form, or confirmed it themselves - any linked guardian may withdraw.
    Otherwise a school-confirmed consent could never be withdrawn by
    anybody, which is a worse failure than this one.
    """

    theirs_to_give = [
        record
        for record in records
        if record.consent_type in wanted
        and record.status is not ConsentStatus.WITHDRAWN
        and record.confirmed_by_parent_id is not None
        and record.confirmed_by_parent_id != parent_id
    ]
    if not theirs_to_give:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "consent_belongs_to_another_guardian",
            "message": (
                "Another of this child's grown-ups gave this permission, so "
                "only they can take it back. Speak to them, or to the school."
            ),
            "consentTypes": sorted(record.consent_type.value for record in theirs_to_give),
        },
    )


@router.post("/consents/withdraw", response_model=RightOutcome)
async def withdraw_consent(
    payload: WithdrawalRequest,
    parent_id: ParentDependency,
    session: DatabaseSession,
) -> RightOutcome:
    """Withdraw, from the parent's own account, at any time.

    Withdrawing the consent a learner cannot start without suspends the child
    immediately, which is what the consent screen promised. Withdrawing only
    the cross-border transfer does not: the child keeps learning, and the
    school is left to decide what to do about material that cannot be sent
    abroad.
    """

    student = await _own_child(session, parent_id, payload.student_id)
    now = datetime.now(UTC)
    wanted = set(payload.consent_types or list(ConsentType))
    records = list(
        await session.scalars(
            select(ConsentRecord).where(ConsentRecord.subject_user_id == student.id)
        )
    )
    _refuse_another_parents_consent(records, wanted=wanted, parent_id=parent_id)
    withdrawn: list[ConsentType] = []
    for record in records:
        if record.consent_type not in wanted:
            continue
        if not await _can_withdraw(session, student.id, parent_id, record):
            raise HTTPException(
                status_code=403,
                detail={"code": "consent_decision_belongs_to_another_guardian",
                        "message": "Only the guardian who gave this consent can withdraw it."},
            )
        if record.status is ConsentStatus.WITHDRAWN:
            continue
        record.status = ConsentStatus.WITHDRAWN
        record.last_actor_user_id = parent_id
        record.last_changed_at = now
        record.last_channel = "parent_portal"
        withdrawn.append(record.consent_type)
    stops_access = REQUIRED_LEARNING_CONSENT in withdrawn
    if stops_access:
        student.status = UserStatus.DEACTIVATED
        student.deactivated_at = now
    request = ParentDataRequest(
        student_id=student.id,
        parent_id=parent_id,
        request_type=ParentRightType.WITHDRAW_CONSENT.value,
        reason=payload.reason,
    )
    session.add(request)
    await _record_refusal(session, parent_id=parent_id, student_id=student.id, now=now)
    await session.commit()
    return RightOutcome(
        request_id=request.id,
        request_type=ParentRightType.WITHDRAW_CONSENT,
        student_id=student.id,
        effect=(
            "Your child has stopped using Nevo. Their school has been told."
            if stops_access
            else "Nevo has stopped doing this. Your child can still use their lessons."
        ),
        withdrawn_types=sorted(withdrawn, key=lambda item: item.value),
        recorded_at=now,
    )


async def _refuse_restoring_another_parents_consent(
    session: AsyncSession,
    records: list[ConsentRecord],
    *,
    wanted: set[ConsentType],
    student_id: UUID,
    parent_id: UUID,
) -> None:
    """A guardian gives back the consent they took away, and nobody else's.

    The mirror of the withdrawal check, and the worse direction of the two:
    without it, adding a guardian would be a way to put a child back into
    processing that the person responsible for them had stopped.

    It asks _can_withdraw rather than keeping a rule of its own. Whoever owns
    the decision owns both halves of it, so the two routes cannot come to
    different answers about whose consent this is - and a rule that is
    tightened later is tightened for restoring at the same time.
    """

    not_theirs = [
        record
        for record in records
        if record.consent_type in wanted
        and record.status is ConsentStatus.WITHDRAWN
        and not await _can_withdraw(session, student_id, parent_id, record)
    ]
    if not not_theirs:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "consent_decision_belongs_to_another_guardian",
            "message": (
                "Another of this child's grown-ups took this permission "
                "back, so only they can give it again. Speak to them, or to "
                "the school."
            ),
            "consentTypes": sorted(record.consent_type.value for record in not_theirs),
        },
    )


@router.post("/consents/restore", response_model=RightOutcome)
async def restore_consent(
    payload: RestoreRequest,
    parent_id: ParentDependency,
    session: DatabaseSession,
) -> RightOutcome:
    """Give back a consent this parent withdrew.

    Withdrawal was terminal, and not on purpose. Three things each correctly
    refuse to overrule a withdrawal - the school's confirm paths, the written
    consent form, and the refusal record that stops the school asking the
    same parent again - and together they left no route back at all. A parent
    who withdrew in November and changed their mind in January had to ask the
    school to do something the school is specifically forbidden to do.

    So the way back is the parent's own, like the way out. Restoring also
    clears the refusal: it exists so the school does not keep asking someone
    who said no, and a parent saying yes here has answered.
    """

    student = await _own_child(session, parent_id, payload.student_id)
    now = datetime.now(UTC)
    wanted = set(payload.consent_types or list(ConsentType))
    records = list(
        await session.scalars(
            select(ConsentRecord).where(ConsentRecord.subject_user_id == student.id)
        )
    )
    await _refuse_restoring_another_parents_consent(
        session,
        records,
        wanted=wanted,
        student_id=student.id,
        parent_id=parent_id,
    )
    restored: list[ConsentType] = []
    for record in records:
        if record.consent_type not in wanted:
            continue
        if record.status is not ConsentStatus.WITHDRAWN:
            continue
        record.status = ConsentStatus.CONFIRMED
        record.confirmed_at = now
        # confirmation_fields_match_status wants one source and exactly the
        # actor that goes with it. The record being restored may have been
        # the school's - confirmed off a paper form, then withdrawn - and
        # leaving its admin id in place beside a parent id satisfies neither
        # branch of that constraint. This consent is now the parent's, given
        # in their own account, so the attribution moves with it.
        record.confirmation_source = ConsentConfirmationSource.PARENT
        record.confirmed_by_parent_id = parent_id
        record.confirmed_by_admin_id = None
        record.confirmed_via = ConsentMethod.DIGITAL
        record.last_actor_user_id = parent_id
        record.last_changed_at = now
        record.last_channel = "parent_portal"
        restored.append(record.consent_type)
    if not restored:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "nothing_to_restore",
                "message": "There is no withdrawn permission here to give back.",
            },
        )
    resumes_access = REQUIRED_LEARNING_CONSENT in restored
    if resumes_access and student.status is UserStatus.DEACTIVATED:
        student.status = UserStatus.ACTIVE
        student.deactivated_at = None
    request = ParentDataRequest(
        student_id=student.id,
        parent_id=parent_id,
        request_type=ParentRightType.RESTORE_CONSENT.value,
        reason=payload.reason,
    )
    session.add(request)
    await _clear_refusal(session, parent_id=parent_id, student_id=student.id)
    await session.commit()
    return RightOutcome(
        request_id=request.id,
        request_type=ParentRightType.RESTORE_CONSENT,
        student_id=student.id,
        effect=(
            "Your child can use Nevo again. Their school has been told."
            if resumes_access
            else "Nevo may do this again. Nothing else about your child's lessons has changed."
        ),
        restored_types=sorted(restored, key=lambda item: item.value),
        recorded_at=now,
    )


async def _clear_refusal(
    session: AsyncSession,
    *,
    parent_id: UUID,
    student_id: UUID,
) -> None:
    """Undo _record_refusal, so the school is not frozen out of asking again.

    The refusal is a standing instruction not to contact this parent about
    this child. A parent who has just restored consent in their own account
    has withdrawn that instruction by answering, and leaving it in place
    would block the next term's request for a consent that is now given.
    """

    parent = await session.get(User, parent_id)
    contact = (parent.email if parent else None) or ""
    if not contact:
        return
    refusals = list(
        await session.scalars(
            select(ConsentRefusal).where(
                ConsentRefusal.student_id == student_id,
                ConsentRefusal.contact_digest == contact_digest(contact),
                ConsentRefusal.reason == ConsentRefusalReason.WITHDRAWN,
            )
        )
    )
    for refusal in refusals:
        await session.delete(refusal)


async def _record_refusal(
    session: AsyncSession,
    *,
    parent_id: UUID,
    student_id: UUID,
    now: datetime,
) -> None:
    """So the school does not send the same request again next term."""

    parent = await session.get(User, parent_id)
    contact = (parent.email if parent else None) or ""
    if not contact:
        return
    digest = contact_digest(contact)
    existing = await session.scalar(
        select(ConsentRefusal).where(
            ConsentRefusal.student_id == student_id,
            ConsentRefusal.contact_digest == digest,
        )
    )
    if existing is not None:
        return
    student = await session.get(User, student_id)
    if student is None or student.school_id is None:
        return
    session.add(
        ConsentRefusal(
            school_id=student.school_id,
            student_id=student_id,
            contact_digest=digest,
            reason=ConsentRefusalReason.WITHDRAWN,
            recorded_at=now,
        )
    )


@router.post("/objections", response_model=RightOutcome)
async def object_to_processing(
    payload: RightRequest,
    parent_id: ParentDependency,
    session: DatabaseSession,
) -> RightOutcome:
    """Object without withdrawing.

    A separate right, and deliberately not a withdrawal: a parent may want
    Nevo to stop doing one thing while their child keeps learning. It is
    recorded for the school to answer rather than acted on automatically,
    because only the school knows what it is being asked to stop.
    """

    return await _record_right(
        session,
        parent_id=parent_id,
        student_id=payload.student_id,
        request_type=ParentRightType.OBJECT,
        reason=payload.reason,
        effect="Your objection has been sent to your child's school to answer.",
    )


@router.post("/data-requests", response_model=RightOutcome)
async def request_data(
    payload: RightRequest,
    parent_id: ParentDependency,
    session: DatabaseSession,
) -> RightOutcome:
    """Ask for the data held about their child."""

    return await _record_right(
        session,
        parent_id=parent_id,
        student_id=payload.student_id,
        request_type=ParentRightType.REQUEST_DATA,
        reason=payload.reason,
        effect="Your request has been sent to your child's school, who must answer it.",
    )


async def _record_right(
    session: AsyncSession,
    *,
    parent_id: UUID,
    student_id: UUID,
    request_type: ParentRightType,
    reason: str | None,
    effect: str,
) -> RightOutcome:
    student = await _own_child(session, parent_id, student_id)
    now = datetime.now(UTC)
    request = ParentDataRequest(
        student_id=student.id,
        parent_id=parent_id,
        request_type=request_type.value,
        reason=reason,
    )
    session.add(request)
    await session.commit()
    return RightOutcome(
        request_id=request.id,
        request_type=request_type,
        student_id=student.id,
        effect=effect,
        recorded_at=now,
    )
