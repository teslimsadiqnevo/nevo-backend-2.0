"""Restricted, content-free safeguarding decisions and erasure audit reads."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from nevo.api.auth import PrincipalDependency
from nevo.api.dependencies import DatabaseSession
from nevo.api.learning_support import require_learning_support
from nevo.api.product_common import require_school_actor
from nevo.api.response_models import CamelResponse
from nevo.db.models.account import User
from nevo.db.models.retention import LearnerPurgeReceipt
from nevo.db.models.safety import ContentSafetyEvent, SafetyReviewAccess

router = APIRouter(prefix="/api/v1", tags=["data compliance"])


class SafetyReviewItem(CamelResponse):
    id: UUID
    phase: str
    action: str
    categories: list[str]
    findings: list[dict[str, str]]
    policy_version: str
    created_at: datetime
    review_label: str | None
    material_expires_at: datetime | None


class SafetyReviewDetail(SafetyReviewItem):
    material: str


class SafetyReviewLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Literal["true_positive", "false_positive", "uncertain"]


@router.get("/safety/lesson-review/weekly-metrics")
async def lesson_safety_weekly_metrics(
    principal: PrincipalDependency,
    session: DatabaseSession,
):
    actor = await require_school_actor(session, principal, roles={"senco_admin"})
    rows = await session.execute(
        select(ContentSafetyEvent.categories, ContentSafetyEvent.review_label).where(
            ContentSafetyEvent.school_id == actor.school_id,
            ContentSafetyEvent.policy_version == "child-safety-2026-11-v2",
            ContentSafetyEvent.created_at >= datetime.now(UTC) - timedelta(days=7),
        )
    )
    counts: dict[str, dict[str, int]] = {}
    for categories, label in rows:
        for category in set(categories or []):
            entry = counts.setdefault(
                category, {"findings": 0, "falsePositives": 0, "truePositives": 0}
            )
            entry["findings"] += 1
            if label == "false_positive":
                entry["falsePositives"] += 1
            elif label == "true_positive":
                entry["truePositives"] += 1
    return {
        "windowDays": 7,
        "categories": [
            {
                "category": category,
                **entry,
                "falsePositiveRate": (
                    entry["falsePositives"] / (entry["falsePositives"] + entry["truePositives"])
                    if entry["falsePositives"] + entry["truePositives"]
                    else None
                ),
                "needsLydiaReview": (
                    entry["truePositives"] == 0
                    and entry["falsePositives"] > 0
                    and entry["falsePositives"] / entry["findings"] > 0.5
                ),
            }
            for category, entry in sorted(counts.items())
        ],
    }


def _review_item(row: ContentSafetyEvent) -> SafetyReviewItem:
    return SafetyReviewItem(
        id=row.id,
        phase=row.phase,
        action=row.action,
        categories=list(row.categories or []),
        findings=list(row.findings or []),
        policy_version=row.policy_version,
        created_at=row.created_at,
        review_label=row.review_label,
        material_expires_at=row.material_expires_at,
    )


@router.get("/safety/lesson-review", response_model=list[SafetyReviewItem])
async def lesson_safety_review_queue(
    principal: PrincipalDependency,
    session: DatabaseSession,
    limit: int = Query(50, ge=1, le=100),
):
    actor = await require_school_actor(session, principal, roles={"senco_admin"})
    rows = await session.scalars(
        select(ContentSafetyEvent)
        .where(
            ContentSafetyEvent.school_id == actor.school_id,
            ContentSafetyEvent.findings.is_not(None),
            ContentSafetyEvent.review_label.is_(None),
        )
        .order_by(ContentSafetyEvent.created_at.desc())
        .limit(limit)
    )
    return [_review_item(row) for row in rows]


@router.get("/safety/lesson-review/{event_id}", response_model=SafetyReviewDetail)
async def lesson_safety_review_detail(
    event_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
):
    actor = await require_school_actor(session, principal, roles={"senco_admin"})
    row = await session.get(ContentSafetyEvent, event_id)
    if (
        row is None
        or row.school_id != actor.school_id
        or row.findings is None
        or row.review_material is None
        or row.material_expires_at is None
        or row.material_expires_at <= datetime.now(UTC)
    ):
        raise HTTPException(404, detail={"code": "safety_review_not_found"})
    session.add(SafetyReviewAccess(event_id=row.id, actor_user_id=actor.id, action="read_material"))
    await session.commit()
    return SafetyReviewDetail(**_review_item(row).model_dump(), material=row.review_material)


@router.post("/safety/lesson-review/{event_id}/label", response_model=SafetyReviewItem)
async def label_lesson_safety_finding(
    event_id: UUID,
    payload: SafetyReviewLabel,
    principal: PrincipalDependency,
    session: DatabaseSession,
):
    actor = await require_school_actor(session, principal, roles={"senco_admin"})
    row = await session.get(ContentSafetyEvent, event_id, with_for_update=True)
    if row is None or row.school_id != actor.school_id or row.findings is None:
        raise HTTPException(404, detail={"code": "safety_review_not_found"})
    if row.review_label is not None:
        raise HTTPException(409, detail={"code": "safety_review_already_labelled"})
    row.review_label = payload.label
    row.reviewed_by = actor.id
    row.reviewed_at = datetime.now(UTC)
    session.add(SafetyReviewAccess(event_id=row.id, actor_user_id=actor.id, action="label"))
    await session.commit()
    return _review_item(row)


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


#: A finding an adult has to act on.
#:
#: Lydia's ruling, 12 November: a name block does not go on the safeguarding
#: list at all. Only categories an adult needs to act on stay.
#:
#: A privacy finding on its own is now allowed through rather than refused
#: (Option A), and putting it in front of a Learning Support holder asks them
#: to act on something nobody decided was wrong. Thirty-one of the
#: thirty-eight blocks ever recorded were exactly this, so the list was mostly
#: noise - and a list that is mostly noise is one nobody reads, which is worse
#: than a short one.
#:
#: A privacy finding alongside anything else still appears, because the
#: anything else is the part that matters.
NOT_ACTIONABLE_ALONE = "privacy_abuse"


def actionable_by_an_adult():
    """A filter for the safeguarding list: everything except a bare name finding."""
    from sqlalchemy import and_, func, not_, or_

    categories = ContentSafetyEvent.categories
    only_a_name = and_(
        func.jsonb_array_length(categories) == 1,
        categories.contains([NOT_ACTIONABLE_ALONE]),
    )
    return or_(categories.is_(None), not_(only_a_name))


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
            actionable_by_an_adult(),
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
        # Not acknowledgeable either, or a holder could clear something the
        # list never showed them and the two reads would disagree.
        or list(row.categories or ()) == [NOT_ACTIONABLE_ALONE]
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
