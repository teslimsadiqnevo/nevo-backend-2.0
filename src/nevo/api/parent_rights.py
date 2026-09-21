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
from nevo.domain.accounts.vocabulary import ConsentStatus, ConsentType, UserStatus
from nevo.domain.consent.vocabulary import (
    REQUIRED_LEARNING_CONSENT,
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
                    )
                    for record in records
                ],
            )
        )
    return out


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
    withdrawn: list[ConsentType] = []
    for record in await session.scalars(
        select(ConsentRecord).where(ConsentRecord.subject_user_id == student.id)
    ):
        if record.consent_type not in wanted:
            continue
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
