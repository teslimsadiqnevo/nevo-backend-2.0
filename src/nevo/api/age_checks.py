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

from datetime import date
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.api.auth import PrincipalDependency
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_common import require_school_actor
from nevo.api.response_models import CamelResponse
from nevo.db.models.account import User
from nevo.db.models.consent_assurance import AgeCheck
from nevo.domain.consent.vocabulary import AgeCheckState

router = APIRouter(prefix="/api/v1/age-checks", tags=["consent"])

SCHOOL_ROLES = {"senco_admin", "other_admin", "teacher"}


class AgeCheckResponse(CamelResponse):
    """A roster note that never discloses the parent's submitted date."""

    id: UUID
    student_id: UUID
    student_first_name: str | None
    #: What the school uploaded, as it was when the check ran.
    school_date_of_birth: date | None
    state: AgeCheckState
    differs: bool
    blocks_access: bool = False


def _view(check: AgeCheck, student: User | None) -> AgeCheckResponse:
    return AgeCheckResponse(
        id=check.id,
        student_id=check.student_id,
        student_first_name=student.first_name if student else None,
        school_date_of_birth=check.school_date_of_birth,
        state=check.state,
        differs=check.state is AgeCheckState.MISMATCH,
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
    views.sort(key=lambda item: (not item.differs, item.student_first_name or ""))
    return views


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
        # The school's corrected roster value is the only thing that clears
        # the note. This is reconciliation, not a staff resolution workflow.
        check.resolved_at = None
        check.resolved_by_user_id = None
    else:
        check.state = AgeCheckState.MISMATCH
        check.agreed_date_of_birth = None
        check.resolved_at = None
        check.resolved_by_user_id = None
