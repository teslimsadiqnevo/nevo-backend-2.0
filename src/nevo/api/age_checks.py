"""Adult DOB reconciliation; no identity documents or staff override."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import ConfigDict, Field, field_validator
from sqlalchemy import select

from nevo.api.auth import PrincipalDependency
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_common import require_school_actor
from nevo.api.response_models import CamelResponse
from nevo.consent.age_assurance import (
    apply_check,
    blocking_reasons,
    capture_band,
    notify_linked_parents,
    notify_unresolved_recheck,
)
from nevo.db.models.account import User
from nevo.db.models.consent import ParentLink
from nevo.db.models.consent_assurance import AgeCheck
from nevo.domain.consent.vocabulary import AgeCheckState

router = APIRouter(prefix="/api/v1/age-checks", tags=["consent"])
SCHOOL_ROLES = {"senco_admin", "other_admin"}


class AgeCheckResponse(CamelResponse):
    id: UUID
    student_id: UUID
    student_first_name: str | None
    parent_name: str | None = None
    school_date_of_birth: date | None
    state: AgeCheckState
    differs: bool
    blocks_access: bool
    clearable: bool = Field(
        description=(
            "True only for an unexpired open hold with both dates present, at most "
            "two calendar years apart and inside the captured enrolled age band. "
            "School recheck and parent reconfirmation are still required; this is "
            "not permission for an administrator to activate the account."
        )
    )
    enrolled_age_band: str | None
    hold_reasons: list[str]
    school_notified_at: datetime | None
    deletion_due_at: datetime | None
    school_rechecked_at: datetime | None
    parent_reconfirmed_at: datetime | None
    parent_notified_at: datetime | None = None


class DateRecheckRequest(CamelResponse):
    model_config = ConfigDict(extra="forbid")

    date_of_birth: date

    @field_validator("date_of_birth")
    @classmethod
    def not_in_future(cls, value):
        if value > datetime.now(UTC).date():
            raise ValueError("Date of birth cannot be in the future")
        return value


def _view(check, student, parent_name=None):
    expired = bool(
        check.school_notified_at
        and datetime.now(UTC) >= check.school_notified_at + timedelta(days=30)
    )
    return AgeCheckResponse(
        id=check.id,
        student_id=check.student_id,
        student_first_name=student.first_name if student else None,
        parent_name=parent_name,
        school_date_of_birth=check.school_date_of_birth,
        state=check.state,
        differs=check.school_date_of_birth != check.parent_date_of_birth,
        blocks_access=check.blocks_access,
        clearable=check.blocks_access and not expired and not blocking_reasons(check),
        enrolled_age_band=check.enrolled_age_band,
        hold_reasons=check.hold_reasons or [],
        school_notified_at=check.school_notified_at,
        deletion_due_at=(
            check.school_notified_at + timedelta(days=30)
            if check.blocks_access and check.school_notified_at
            else None
        ),
        school_rechecked_at=check.school_rechecked_at,
        parent_reconfirmed_at=check.parent_reconfirmed_at,
        parent_notified_at=check.parent_notified_at,
    )


@router.get("", response_model=list[AgeCheckResponse])
async def list_age_checks(
    principal: PrincipalDependency, session: DatabaseSession, state: AgeCheckState | None = None
):
    actor = await require_school_actor(session, principal, roles=SCHOOL_ROLES)
    query = select(AgeCheck).where(AgeCheck.school_id == actor.school_id)
    if state is not None:
        query = query.where(AgeCheck.state == state)
    checks = list(await session.scalars(query.order_by(AgeCheck.created_at.desc())))
    return [
        _view(check, await session.get(User, check.student_id), await _parent_name(session, check))
        for check in checks
    ]


async def _parent_name(session, check):
    return await session.scalar(
        select(ParentLink.parent_name)
        .where(ParentLink.student_id == check.student_id, ParentLink.school_id == check.school_id)
        .order_by(ParentLink.created_at)
        .limit(1)
    )


async def _check(session, check_id):
    student_id = await session.scalar(select(AgeCheck.student_id).where(AgeCheck.id == check_id))
    if student_id is None:
        raise HTTPException(404, detail={"code": "age_check_not_found"})
    student = await session.get(User, student_id, with_for_update=True)
    check = await session.get(AgeCheck, check_id, with_for_update=True)
    if student is None or check is None:
        raise HTTPException(404, detail={"code": "age_check_not_found"})
    return check, student


def _open_check(check, now):
    if not check.blocks_access:
        raise HTTPException(409, detail={"code": "age_check_not_pending"})
    if check.school_notified_at and now >= check.school_notified_at + timedelta(days=30):
        raise HTTPException(410, detail={"code": "age_check_expired"})


REFUSALS = {
    403: {"description": "Authorised school administrator or linked parent required"},
    404: {"description": "age_check_not_found"},
    409: {"description": "school_recheck_required or age_check_not_pending"},
    410: {"description": "age_check_expired"},
}


@router.post("/{age_check_id}/school-recheck", response_model=AgeCheckResponse, responses=REFUSALS)
async def school_recheck(
    age_check_id: UUID,
    payload: DateRecheckRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
):
    actor = await require_school_actor(session, principal, roles=SCHOOL_ROLES)
    check, student = await _check(session, age_check_id)
    if check.school_id != actor.school_id:
        raise HTTPException(404, detail={"code": "age_check_not_found"})
    now = datetime.now(UTC)
    _open_check(check, now)
    check.school_date_of_birth = payload.date_of_birth
    check.school_rechecked_at, check.school_rechecked_by = now, actor.id
    check.parent_reconfirmed_at = check.parent_reconfirmed_by = None
    await capture_band(session, check, now.date())
    await apply_check(session, check, student, now)
    if check.blocks_access:
        await notify_linked_parents(session, check, now)
    result = _view(check, student, await _parent_name(session, check))
    await session.commit()
    return result


@router.post(
    "/{age_check_id}/resend-parent-notice",
    response_model=AgeCheckResponse,
    responses={409: {"description": "school_recheck_required or parent_account_unavailable"}},
)
async def resend_parent_age_check_notice(
    age_check_id: UUID, principal: PrincipalDependency, session: DatabaseSession,
):
    actor = await require_school_actor(session, principal, roles=SCHOOL_ROLES)
    check, student = await _check(session, age_check_id)
    if check.school_id != actor.school_id:
        raise HTTPException(404, detail={"code": "age_check_not_found"})
    now = datetime.now(UTC)
    _open_check(check, now)
    if check.school_rechecked_at is None:
        raise HTTPException(409, detail={"code": "school_recheck_required"})
    if check.parent_notified_at and now - check.parent_notified_at < timedelta(minutes=5):
        raise HTTPException(429, detail={"code": "parent_notice_recently_sent"})
    if not await notify_linked_parents(session, check, now):
        raise HTTPException(409, detail={"code": "parent_account_unavailable"})
    result = _view(check, student, await _parent_name(session, check))
    await session.commit()
    return result


@router.get("/parent", response_model=list[AgeCheckResponse])
async def parent_age_checks(principal: PrincipalDependency, session: DatabaseSession):
    if principal.role != "parent_guardian":
        raise HTTPException(403, detail={"code": "parent_account_required"})
    checks = list(
        await session.scalars(
            select(AgeCheck)
            .join(ParentLink, ParentLink.student_id == AgeCheck.student_id)
            .where(ParentLink.parent_id == principal.user_id)
            .distinct()
        )
    )
    return [
        _view(check, await session.get(User, check.student_id), await _parent_name(session, check))
        for check in checks
    ]


@router.post(
    "/{age_check_id}/parent-reconfirm", response_model=AgeCheckResponse, responses=REFUSALS
)
async def parent_reconfirm(
    age_check_id: UUID,
    payload: DateRecheckRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
):
    if principal.role != "parent_guardian":
        raise HTTPException(403, detail={"code": "parent_account_required"})
    check, student = await _check(session, age_check_id)
    link = await session.scalar(
        select(ParentLink.id).where(
            ParentLink.student_id == check.student_id, ParentLink.parent_id == principal.user_id
        )
    )
    if link is None:
        raise HTTPException(404, detail={"code": "age_check_not_found"})
    now = datetime.now(UTC)
    _open_check(check, now)
    if check.school_rechecked_at is None:
        raise HTTPException(409, detail={"code": "school_recheck_required"})
    check.parent_date_of_birth = payload.date_of_birth
    check.parent_reconfirmed_at, check.parent_reconfirmed_by = now, principal.user_id
    await apply_check(session, check, student, now, parent_actor=principal.user_id)
    if check.blocks_access:
        await notify_unresolved_recheck(session, check, now)
    result = _view(check, student, await _parent_name(session, check))
    await session.commit()
    return result
