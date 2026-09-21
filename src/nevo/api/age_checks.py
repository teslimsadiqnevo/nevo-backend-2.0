"""Two dates of birth, compared, and the exceptions a person has to settle.

A date of birth decides whether a child should be offered this product at
all, and it came from one place — a line somebody typed into a roster — with
nothing to check it against. The parent is now asked for it too, on the
consent screen, and the two are compared.

A disagreement is an exception, not a rule for software to apply. Nevo does
not prefer the school's date over the parent's or the other way round, and it
never asks the child. It blocks access, tells the school, and waits for a
person to settle it with both sides.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.api.auth import PrincipalDependency
from nevo.api.casing import CAMEL_CONFIG
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_common import require_school_actor
from nevo.api.response_models import CamelResponse
from nevo.db.models.account import User
from nevo.db.models.consent_assurance import AgeCheck
from nevo.domain.consent.vocabulary import AgeCheckState

router = APIRouter(prefix="/api/v1/age-checks", tags=["consent"])

SCHOOL_ROLES = {"senco_admin", "other_admin", "teacher"}


class AgeCheckResponse(CamelResponse):
    """One child's two dates, and where the disagreement stands."""

    id: UUID
    student_id: UUID
    student_first_name: str | None
    #: What the school uploaded, as it was when the check ran.
    school_date_of_birth: date | None
    #: What the parent confirmed.
    parent_date_of_birth: date | None
    state: AgeCheckState
    agreed_date_of_birth: date | None
    resolution_note: str | None
    resolved_by: UUID | None
    resolved_at: datetime | None
    #: True while this keeps the child out of the product.
    blocks_access: bool


class AgeCheckResolution(BaseModel):
    """What the school agreed with the parent.

    The date is required: closing an exception without saying what the answer
    is leaves the roster holding a figure two people already disagreed about.
    """

    model_config = CAMEL_CONFIG

    agreed_date_of_birth: Annotated[date, Field(alias="agreedDateOfBirth")]
    #: How it was settled and with whom. Short, and for the school's own
    #: record of having done it.
    note: Annotated[str | None, Field(default=None, max_length=500)] = None


def _view(check: AgeCheck, student: User | None) -> AgeCheckResponse:
    return AgeCheckResponse(
        id=check.id,
        student_id=check.student_id,
        student_first_name=student.first_name if student else None,
        school_date_of_birth=check.school_date_of_birth,
        parent_date_of_birth=check.parent_date_of_birth,
        state=check.state,
        agreed_date_of_birth=check.agreed_date_of_birth,
        resolution_note=check.resolution_note,
        resolved_by=check.resolved_by_user_id,
        resolved_at=check.resolved_at,
        blocks_access=check.blocks_access,
    )


@router.get("", response_model=list[AgeCheckResponse])
async def list_age_checks(
    principal: PrincipalDependency,
    session: DatabaseSession,
    state: AgeCheckState | None = None,
) -> list[AgeCheckResponse]:
    """The exception queue. Mismatches first, because they block children."""

    actor = await require_school_actor(session, principal, roles=SCHOOL_ROLES)
    query = select(AgeCheck).where(AgeCheck.school_id == actor.school_id)
    if state is not None:
        query = query.where(AgeCheck.state == state)
    checks = list(await session.scalars(query.order_by(AgeCheck.created_at.desc())))
    students = {
        student.id: student
        for student in await session.scalars(
            select(User).where(User.id.in_([check.student_id for check in checks]))
        )
    }
    views = [_view(check, students.get(check.student_id)) for check in checks]
    views.sort(key=lambda item: (not item.blocks_access, item.student_first_name or ""))
    return views


@router.post("/{age_check_id}/resolve", response_model=AgeCheckResponse)
async def resolve_age_check(
    age_check_id: UUID,
    payload: AgeCheckResolution,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> AgeCheckResponse:
    """Close an exception with the date both sides agreed.

    The agreed date is written back to the roster, so the record the product
    uses from here on is the one two people settled on rather than the one
    that was typed. Who closed it and when is kept, because a school has to
    be able to show that the disagreement was dealt with and not overridden.
    """

    actor = await require_school_actor(session, principal, roles=SCHOOL_ROLES)
    check = await session.get(AgeCheck, age_check_id)
    if check is None or check.school_id != actor.school_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Age check not found")
    if payload.agreed_date_of_birth > datetime.now(UTC).date():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "date_in_the_future",
                "message": "That date has not happened yet. Check it with the parent.",
            },
        )
    now = datetime.now(UTC)
    check.agreed_date_of_birth = payload.agreed_date_of_birth
    check.resolution_note = payload.note
    check.resolved_by_user_id = actor.id
    check.resolved_at = now
    check.state = AgeCheckState.RESOLVED
    student = await session.get(User, check.student_id)
    if student is not None:
        student.date_of_birth = payload.agreed_date_of_birth
    await session.commit()
    return _view(check, student)


async def age_check_blocks(session: AsyncSession, student_id: UUID) -> bool:
    """Whether an unsettled disagreement keeps this child out.

    Asked by the entry flow, so the block is the API's. A child whose two
    dates of birth disagree is a child nobody is sure is old enough to be
    here, and that is settled before they start rather than after.
    """

    state = await session.scalar(select(AgeCheck.state).where(AgeCheck.student_id == student_id))
    return state is AgeCheckState.MISMATCH
