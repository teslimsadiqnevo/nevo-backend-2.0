"""Restricted, content-free safeguarding decisions and erasure audit reads."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from nevo.api.auth import PrincipalDependency
from nevo.api.dependencies import DatabaseSession
from nevo.api.learning_support import require_learning_support
from nevo.api.product_common import require_school_actor
from nevo.api.response_models import CamelResponse
from nevo.db.models.account import User
from nevo.db.models.retention import LearnerPurgeReceipt
from nevo.db.models.safety import ContentSafetyEvent

router = APIRouter(prefix="/api/v1", tags=["data compliance"])


class SafetyEventResponse(CamelResponse):
    id: UUID
    student_id: UUID | None
    phase: str
    action: str
    categories: list[str]
    policy_version: str
    created_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by: UUID | None
    student_name: str
    acknowledged_by_name: str | None


async def _safeguarding_actor(session, principal):
    actor = await require_school_actor(
        session, principal, roles={"teacher", "other_admin", "senco_admin"}
    )
    await require_learning_support(session, actor)
    return actor


async def _event(session, row):
    student = await session.get(User, row.student_id)
    reviewer = await session.get(User, row.acknowledged_by) if row.acknowledged_by else None
    return SafetyEventResponse(
        **{
            name: getattr(row, name)
            for name in SafetyEventResponse.model_fields
            if name not in {"student_name", "acknowledged_by_name"}
        },
        student_name=" ".join(filter(None, (student.first_name, student.last_name))),
        acknowledged_by_name=(
            " ".join(filter(None, (reviewer.first_name, reviewer.last_name))) if reviewer else None
        ),
    )


@router.get(
    "/safety/events",
    response_model=list[SafetyEventResponse],
    responses={403: {"description": "learning_support_role_required"}},
)
async def safety_events(
    principal: PrincipalDependency,
    session: DatabaseSession,
    pending_only: bool = True,
    limit: int = Query(50, ge=1, le=200),
    before: datetime | None = None,
):
    """Learning Support holders only; never child questions or responses."""
    actor = await _safeguarding_actor(session, principal)
    query = (
        select(ContentSafetyEvent)
        .join(User, User.id == ContentSafetyEvent.student_id)
        .where(
            ContentSafetyEvent.school_id == actor.school_id,
            User.school_id == actor.school_id,
            User.role == "student",
            ContentSafetyEvent.action.in_(["block", "safeguard"]),
        )
    )
    if pending_only:
        query = query.where(ContentSafetyEvent.acknowledged_at.is_(None))
    if before is not None:
        query = query.where(ContentSafetyEvent.created_at < before)
    rows = await session.scalars(query.order_by(ContentSafetyEvent.created_at.desc()).limit(limit))
    return [await _event(session, row) for row in rows]


@router.post(
    "/safety/events/{event_id}/acknowledge",
    response_model=SafetyEventResponse,
    responses={
        403: {"description": "learning_support_role_required"},
        404: {"description": "safety_event_not_found"},
    },
)
async def acknowledge_safety(
    event_id: UUID, principal: PrincipalDependency, session: DatabaseSession
):
    actor = await _safeguarding_actor(session, principal)
    row = await session.get(ContentSafetyEvent, event_id, with_for_update=True)
    student = await session.get(User, row.student_id) if row and row.student_id else None
    if (
        row is None
        or row.school_id != actor.school_id
        or row.action not in {"block", "safeguard"}
        or student is None
        or student.school_id != actor.school_id
        or student.role.value != "student"
    ):
        raise HTTPException(404, detail={"code": "safety_event_not_found"})
    if row.acknowledged_at is None:
        row.acknowledged_at, row.acknowledged_by = datetime.now(UTC), actor.id
    await session.commit()
    return await _event(session, row)


class RetentionState(CamelResponse):
    student_id: UUID
    purpose_ended_at: datetime | None
    purge_due_at: datetime | None
    purged_at: datetime | None


@router.post("/students/{student_id}/retention/end-purpose", response_model=RetentionState)
async def end_purpose(student_id: UUID, principal: PrincipalDependency, session: DatabaseSession):
    """Record cessation now; erasure cannot be undone after the purge."""
    actor = await require_school_actor(session, principal, roles={"senco_admin"})
    student = await session.get(User, student_id, with_for_update=True)
    if student is None or student.school_id != actor.school_id or student.role.value != "student":
        raise HTTPException(404, detail={"code": "student_not_found"})
    if student.purpose_ended_at is None:
        student.purpose_ended_at = datetime.now(UTC)
    student.status = "deactivated"
    student.deactivated_at = student.deactivated_at or student.purpose_ended_at
    await session.flush()
    await session.refresh(student)
    result = RetentionState(
        student_id=student.id,
        purpose_ended_at=student.purpose_ended_at,
        purge_due_at=student.retention_due_at,
        purged_at=student.retention_purged_at,
    )
    await session.commit()
    return result


class PurgeReceiptResponse(CamelResponse):
    id: UUID
    status: str
    counts: dict[str, int]
    error_code: str | None
    completed_at: datetime | None
    created_at: datetime


@router.get("/retention/receipts", response_model=list[PurgeReceiptResponse])
async def purge_receipts(
    principal: PrincipalDependency,
    session: DatabaseSession,
    limit: int = Query(50, ge=1, le=200),
    before: datetime | None = None,
):
    actor = await require_school_actor(session, principal, roles={"senco_admin"})
    query = select(LearnerPurgeReceipt).where(LearnerPurgeReceipt.school_id == actor.school_id)
    if before is not None:
        query = query.where(LearnerPurgeReceipt.created_at < before)
    rows = await session.scalars(query.order_by(LearnerPurgeReceipt.created_at.desc()).limit(limit))
    return [
        PurgeReceiptResponse(
            **{name: getattr(row, name) for name in PurgeReceiptResponse.model_fields}
        )
        for row in rows
    ]
