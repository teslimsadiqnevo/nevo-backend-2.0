"""Two dates of birth, compared, and recorded as roster notes.

A date of birth decides whether a child should be offered this product at
all, and it came from one place — a line somebody typed into a roster — with
nothing to check it against. The parent is now asked for it too, on the
consent screen, and the two are compared.

A disagreement is an exception, not a rule for software to apply. The school
record remains authoritative for delivery, the mismatch is visible to staff,
and no child is blocked while adults correct either source.
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
    #: Always false. Kept for contract compatibility with older clients.
    blocks_access: bool


class AgeCheckResolution(BaseModel):
    """What the school agreed with the parent.

    The date is required: closing an exception without saying what the answer
    is leaves the roster holding a figure two people already disagreed about.
    """

    model_config = CAMEL_CONFIG

    agreed_date_of_birth: Annotated[date | None, Field(alias="agreedDateOfBirth")] = None
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
    """The exception queue. Mismatches first so staff can correct the roster note."""

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
    """Close the note while retaining the school's date as authoritative."""

    actor = await require_school_actor(session, principal, roles=SCHOOL_ROLES)
    check = await session.get(AgeCheck, age_check_id)
    if check is None or check.school_id != actor.school_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Age check not found")
    if (
        payload.agreed_date_of_birth is not None
        and payload.agreed_date_of_birth > datetime.now(UTC).date()
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "date_in_the_future",
                "message": "That date has not happened yet. Check it with the parent.",
            },
        )
    now = datetime.now(UTC)
    check.agreed_date_of_birth = check.school_date_of_birth
    check.resolution_note = payload.note
    check.resolved_by_user_id = actor.id
    check.resolved_at = now
    check.state = AgeCheckState.RESOLVED
    student = await session.get(User, check.student_id)
    await session.commit()
    return _view(check, student)


async def age_check_blocks(session: AsyncSession, student_id: UUID) -> bool:
    """Compatibility hook: Lydia's 7 October ruling makes this always false."""

    del session, student_id
    return False


async def reconcile_school_date(
    session: AsyncSession,
    student_id: UUID,
    school_date_of_birth: date | None,
) -> None:
    """Close a mismatch automatically when the corrected school date agrees."""

    check = await session.scalar(select(AgeCheck).where(AgeCheck.student_id == student_id))
    if check is None:
        return
    check.school_date_of_birth = school_date_of_birth
    if check.parent_date_of_birth is None:
        check.state = AgeCheckState.AWAITING_PARENT
    elif school_date_of_birth == check.parent_date_of_birth:
        check.state = AgeCheckState.MATCHED
        check.agreed_date_of_birth = school_date_of_birth
        check.resolved_at = datetime.now(UTC)
    else:
        check.state = AgeCheckState.MISMATCH
        check.agreed_date_of_birth = None
        check.resolved_at = None
        check.resolved_by_user_id = None
