"""The review a teacher has to perform before a lesson can be assigned.

The product told a teacher that parts of a lesson needed review and then gave
them nothing to review with: key points rendered as cards that could not be
opened, no source text behind them, and no accept, amend or remove anywhere.
Assignment stayed refused, which blocked the one action the product is sold
on.

Two rulings shape what is here. Only points Nevo could not ground in the
segment they came from are outstanding, so a teacher never clicks through a
whole lesson to assign it. And what a teacher writes is kept beside what Nevo
extracted rather than over it, so the screen can always show both.
"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.api.auth import PrincipalDependency
from nevo.api.casing import CAMEL_CONFIG
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_common import require_school_actor
from nevo.api.response_models import CamelResponse
from nevo.db.models.account import User
from nevo.db.models.content import Lesson, LessonKeyPoint, LessonSegment
from nevo.db.models.lesson_signoff import LessonReviewSignoff
from nevo.domain.intelligence.vocabulary import KeyPointConfidence, KeyPointReviewState

router = APIRouter(prefix="/api/v1", tags=["learning product"])

REVIEW_ROLES = {"teacher", "senco_admin", "other_admin"}

#: The states that mean a person has dealt with this point.
RESOLVED_STATES = {
    KeyPointReviewState.ACCEPTED,
    KeyPointReviewState.AMENDED,
    KeyPointReviewState.REMOVED,
}


class KeyPointResponse(CamelResponse):
    """One key point, and everything the card needs when it is expanded."""

    id: UUID
    segment_id: UUID
    segment_title: str | None
    position: int
    #: What the lesson says now: the teacher's wording where they wrote one.
    text: str
    #: What Nevo read, kept even after a teacher rewrites it.
    extracted_text: str
    #: The teacher's wording, or null if they have not written one.
    amended_text: str | None
    #: The segment text this was drawn from, as it was when it was drawn.
    source_text: str
    confidence: KeyPointConfidence
    review_state: KeyPointReviewState
    #: True while this point is what stands between the lesson and a class.
    outstanding: bool
    resolved_at: datetime | None
    resolved_by: UUID | None


class ReviewSignoffResponse(CamelResponse):
    id: UUID
    kind: Literal["key_points", "rewrites"]
    approved_by: UUID | None
    approved_by_name: str
    approved_at: datetime
    content_hash: str
    current: bool


class LessonReviewResponse(CamelResponse):
    """The lesson's review state, which is what LR-04 counts down."""

    lesson_id: UUID
    title: str
    #: How many points are still waiting for a teacher. Zero means ready.
    outstanding_count: int
    key_point_count: int
    #: True when nothing is outstanding. The screen enables Assign on this
    #: rather than counting the list itself, so client and server cannot
    #: disagree about when a lesson is ready.
    ready_to_assign: bool
    key_points: list[KeyPointResponse]
    key_points_content_hash: str = ""
    rewrites_content_hash: str = ""
    key_point_approval: ReviewSignoffResponse | None = None
    rewrite_approval: ReviewSignoffResponse | None = None
    missing_key_point_segment_ids: list[UUID] = Field(default_factory=list)
    rewrite_count: int = 0
    pending_rewrite_count: int = 0
    review_complete: bool = False


class KeyPointAmendment(BaseModel):
    model_config = CAMEL_CONFIG

    text: Annotated[str, Field(min_length=1, max_length=400)]


async def _key_point_rows(
    session: AsyncSession,
    lesson_id: UUID,
) -> list[tuple[LessonKeyPoint, str | None]]:
    rows = await session.execute(
        select(LessonKeyPoint, LessonSegment.title)
        .join(LessonSegment, LessonSegment.id == LessonKeyPoint.segment_id)
        .where(LessonKeyPoint.lesson_id == lesson_id)
        .order_by(LessonSegment.sequence_order, LessonKeyPoint.position)
    )
    return [(point, title) for point, title in rows.all()]


def _view(point: LessonKeyPoint, segment_title: str | None) -> KeyPointResponse:
    return KeyPointResponse(
        id=point.id,
        segment_id=point.segment_id,
        segment_title=segment_title,
        position=point.position,
        text=point.text,
        extracted_text=point.extracted_text,
        amended_text=point.amended_text,
        source_text=point.source_text,
        confidence=point.confidence,
        review_state=point.review_state,
        outstanding=point.review_state is KeyPointReviewState.UNSURE,
        resolved_at=point.resolved_at,
        resolved_by=point.resolved_by,
    )


def _review(
    lesson: Lesson,
    rows: list[tuple[LessonKeyPoint, str | None]],
) -> LessonReviewResponse:
    views = [_view(point, title) for point, title in rows]
    outstanding = sum(1 for view in views if view.outstanding)
    return LessonReviewResponse(
        lesson_id=lesson.id,
        title=lesson.title,
        outstanding_count=outstanding,
        key_point_count=len(views),
        ready_to_assign=outstanding == 0,
        key_points=views,
    )


async def _lesson_for_review(
    session: AsyncSession,
    principal: PrincipalDependency,
    lesson_id: UUID,
) -> tuple[Lesson, User]:
    actor = await require_school_actor(session, principal, roles=REVIEW_ROLES)
    lesson = await session.get(Lesson, lesson_id, with_for_update=True)
    if lesson is None or lesson.school_id != actor.school_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found")
    return lesson, actor


async def _point_for_review(
    session: AsyncSession,
    lesson: Lesson,
    key_point_id: UUID,
) -> LessonKeyPoint:
    point = await session.get(LessonKeyPoint, key_point_id)
    if point is None or point.lesson_id != lesson.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key point not found")
    return point


def _resolve(point: LessonKeyPoint, *, state: KeyPointReviewState, actor: User) -> None:
    point.review_state = state
    point.resolved_at = datetime.now(UTC)
    point.resolved_by = actor.id


@router.get("/lessons/{lesson_id}/review", response_model=LessonReviewResponse)
async def read_lesson_review(
    lesson_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> LessonReviewResponse:
    """Everything the lesson page's needs-review state renders.

    One read rather than one per card: the screen shows the cards and the
    remaining count together, and a teacher opening a card should not cost a
    request to find out what Nevo read.
    """

    lesson, _ = await _lesson_for_review(session, principal, lesson_id)
    return await _review_result(session, lesson)


@router.post(
    "/lessons/{lesson_id}/key-points/{key_point_id}/accept",
    response_model=LessonReviewResponse,
    deprecated=True,
)
async def accept_key_point(
    lesson_id: UUID,
    key_point_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> LessonReviewResponse:
    """A teacher read the point and let it stand."""

    lesson, actor = await _lesson_for_review(session, principal, lesson_id)
    point = await _point_for_review(session, lesson, key_point_id)
    if point.review_state not in RESOLVED_STATES:
        _resolve(point, state=KeyPointReviewState.ACCEPTED, actor=actor)
        await session.commit()
    return await _review_result(session, lesson)


@router.patch(
    "/lessons/{lesson_id}/key-points/{key_point_id}",
    response_model=LessonReviewResponse,
)
async def amend_key_point(
    lesson_id: UUID,
    key_point_id: UUID,
    payload: KeyPointAmendment,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> LessonReviewResponse:
    """A teacher rewrote the point.

    The new wording goes in the segment the child reads as well, because a key
    point a teacher corrected and a child still sees the old version of is
    worse than no correction.
    """

    lesson, actor = await _lesson_for_review(session, principal, lesson_id)
    point = await _point_for_review(session, lesson, key_point_id)
    if point.text != payload.text.strip():
        await _invalidate_signoffs(session, lesson.id, "key_points")
    point.amended_text = payload.text.strip()
    _resolve(point, state=KeyPointReviewState.AMENDED, actor=actor)
    await _write_through(session, point)
    await session.commit()
    return await _review_result(session, lesson)


@router.delete(
    "/lessons/{lesson_id}/key-points/{key_point_id}",
    response_model=LessonReviewResponse,
)
async def remove_key_point(
    lesson_id: UUID,
    key_point_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> LessonReviewResponse:
    """A teacher took the point out of the lesson.

    The row stays, marked removed. A deleted row would lose the fact that Nevo
    read something a teacher rejected, which is the record that says whether
    the parser is getting better.
    """

    lesson, actor = await _lesson_for_review(session, principal, lesson_id)
    point = await _point_for_review(session, lesson, key_point_id)
    if point.review_state != KeyPointReviewState.REMOVED:
        await _invalidate_signoffs(session, lesson.id, "key_points")
    _resolve(point, state=KeyPointReviewState.REMOVED, actor=actor)
    await _write_through(session, point)
    await session.commit()
    return await _review_result(session, lesson)


async def _write_through(session: AsyncSession, point: LessonKeyPoint) -> None:
    """Put the teacher's decision into the variant a child is served."""

    segment = await session.get(LessonSegment, point.segment_id)
    if segment is None:
        return
    points = await session.scalars(
        select(LessonKeyPoint)
        .where(LessonKeyPoint.segment_id == point.segment_id)
        .order_by(LessonKeyPoint.position)
    )
    kept = [item.text for item in points if item.review_state is not KeyPointReviewState.REMOVED]
    segment.text_variant = {**(segment.text_variant or {}), "keyPoints": kept}


class BulkReviewRequest(BaseModel):
    model_config = CAMEL_CONFIG

    expected_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class MissingKeyPointWrite(BaseModel):
    model_config = CAMEL_CONFIG

    action: Literal["add", "omit"]
    text: str | None = Field(default=None, max_length=400)

    @model_validator(mode="after")
    def valid_text(self):
        self.text = self.text.strip() if self.text is not None else None
        if self.action == "add" and not self.text:
            raise ValueError("Write a key point before adding it.")
        if self.action == "omit" and self.text:
            raise ValueError("Omitting a key point does not take text.")
        return self


class RewriteEdit(BaseModel):
    body: str = Field(min_length=1, max_length=50000)

    @field_validator("body")
    @classmethod
    def nonempty(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Rewrite wording cannot be blank.")
        return value


def _hash(snapshot):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest()


async def _invalidate_signoffs(session, lesson_id, kind):
    await session.execute(
        update(LessonReviewSignoff)
        .where(
            LessonReviewSignoff.lesson_id == lesson_id,
            LessonReviewSignoff.kind == kind,
            LessonReviewSignoff.invalidated_at.is_(None),
        )
        .values(invalidated_at=datetime.now(UTC))
    )


async def _review_material(session, lesson):
    rows = await _key_point_rows(session, lesson.id)
    segments = list(
        await session.scalars(
            select(LessonSegment)
            .where(LessonSegment.lesson_id == lesson.id)
            .order_by(LessonSegment.sequence_order, LessonSegment.id)
        )
    )
    points = [
        {
            "id": str(point.id),
            "segmentId": str(point.segment_id),
            "text": point.text,
            "source": point.source_text,
            "omitted": point.review_state == KeyPointReviewState.REMOVED,
        }
        for point, _ in rows
    ]
    sources = [{"segmentId": str(segment.id), "body": segment.body} for segment in segments]
    key_material = [*sources, *points]
    rewrites = []
    for segment in segments:
        for kind in ("simplified", "expanded"):
            item = (segment.depth_variants or {}).get(kind)
            if isinstance(item, dict) and item.get("body"):
                rewrites.append(
                    {
                        "segmentId": str(segment.id),
                        "kind": kind,
                        "body": item["body"],
                        "source": segment.body,
                    }
                )
    return rows, segments, key_material, rewrites


async def _review_result(session, lesson):
    from nevo.api.lesson_contracts import depth_approved

    rows, segments, points, rewrites = await _review_material(session, lesson)
    result = _review(lesson, rows)
    hashes = {"key_points": _hash(points), "rewrites": _hash(rewrites)}
    approvals = {}
    for record in await session.scalars(
        select(LessonReviewSignoff)
        .where(LessonReviewSignoff.lesson_id == lesson.id)
        .order_by(LessonReviewSignoff.approved_at.desc(), LessonReviewSignoff.id.desc())
    ):
        approvals.setdefault(
            record.kind,
            ReviewSignoffResponse(
                id=record.id,
                kind=record.kind,
                approved_by=record.approved_by,
                approved_by_name=record.approved_by_name,
                approved_at=record.approved_at,
                content_hash=record.content_hash,
                current=record.content_hash == hashes[record.kind]
                and record.invalidated_at is None,
            ),
        )
    return result.model_copy(
        update={
            "key_points_content_hash": hashes["key_points"],
            "rewrites_content_hash": hashes["rewrites"],
            "key_point_approval": approvals.get("key_points"),
            "rewrite_approval": approvals.get("rewrites"),
            "missing_key_point_segment_ids": [
                segment.id
                for segment in segments
                if not any(point.segment_id == segment.id for point, _ in rows)
            ],
            "rewrite_count": len(rewrites),
            "pending_rewrite_count": sum(
                not depth_approved((segment.depth_variants or {}).get(kind))
                for segment in segments
                for kind in ("simplified", "expanded")
                if isinstance((segment.depth_variants or {}).get(kind), dict)
                and (segment.depth_variants or {})[kind].get("body")
            ),
            "review_complete": bool(approvals.get("key_points") and approvals["key_points"].current)
            and (not rewrites or bool(approvals.get("rewrites") and approvals["rewrites"].current)),
        }
    )


async def _bulk_approve(session, lesson, actor, payload, kind):
    rows, segments, points, rewrites = await _review_material(session, lesson)
    if lesson.status not in {"completed", "completed_with_review"} or not segments:
        raise HTTPException(
            409,
            detail={
                "code": "lesson_not_ready_for_review",
                "message": "Wait for the lesson to finish processing before approving.",
            },
        )
    material = points if kind == "key_points" else rewrites
    digest = _hash(material)
    if digest != payload.expected_content_hash:
        raise HTTPException(
            409,
            detail={
                "code": "review_content_changed",
                "message": "The lesson changed. Read it again before approving.",
            },
        )
    if kind == "key_points" and any(
        not any(point.segment_id == segment.id for point, _ in rows) for segment in segments
    ):
        raise HTTPException(
            409,
            detail={
                "code": "key_point_decision_required",
                "message": "Add or omit each missing key point before approving.",
            },
        )
    if kind == "rewrites" and not rewrites:
        raise HTTPException(
            409,
            detail={
                "code": "no_rewrites_to_approve",
                "message": "This lesson has no rewrites to approve.",
            },
        )
    latest = await session.scalar(
        select(LessonReviewSignoff)
        .where(LessonReviewSignoff.lesson_id == lesson.id, LessonReviewSignoff.kind == kind)
        .order_by(LessonReviewSignoff.approved_at.desc(), LessonReviewSignoff.id.desc())
        .limit(1)
    )
    now = datetime.now(UTC)
    reuse = (
        latest is not None
        and latest.content_hash == digest
        and latest.approved_by == actor.id
        and latest.invalidated_at is None
    )
    if not reuse:
        session.add(
            LessonReviewSignoff(
                lesson_id=lesson.id,
                kind=kind,
                approved_by=actor.id,
                approved_by_name=" ".join(
                    part for part in (actor.first_name, actor.last_name) if part
                )
                or actor.email
                or str(actor.id),
                approved_at=now,
                content_hash=digest,
                content_snapshot=material,
            )
        )
    else:
        now = latest.approved_at
    reviewer = latest.approved_by if reuse else actor.id
    if kind == "key_points":
        for point, _ in rows:
            if point.review_state != KeyPointReviewState.REMOVED:
                point.review_state = (
                    KeyPointReviewState.AMENDED
                    if point.amended_text
                    else KeyPointReviewState.ACCEPTED
                )
                point.resolved_by, point.resolved_at = reviewer, now
    else:
        for segment in segments:
            variants = dict(segment.depth_variants or {})
            for key in ("simplified", "expanded"):
                if isinstance(variants.get(key), dict) and variants[key].get("body"):
                    variants[key] = {
                        **variants[key],
                        "reviewStatus": "approved",
                        "reviewedBy": str(reviewer),
                        "reviewedAt": now.isoformat(),
                    }
            segment.depth_variants = variants
    await session.commit()
    return await _review_result(session, lesson)


@router.post(
    "/lessons/{lesson_id}/key-points/approve-all",
    response_model=LessonReviewResponse,
    responses={409: {"description": "review_content_changed or key_point_decision_required"}},
)
async def approve_all_key_points(
    lesson_id: UUID,
    payload: BulkReviewRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
):
    """One professional sign-off over the lesson's complete key-point set."""
    lesson, actor = await _lesson_for_review(session, principal, lesson_id)
    return await _bulk_approve(session, lesson, actor, payload, "key_points")


@router.post(
    "/lessons/{lesson_id}/rewrites/approve-all",
    response_model=LessonReviewResponse,
    responses={409: {"description": "review_content_changed or no_rewrites_to_approve"}},
)
async def approve_all_rewrites(
    lesson_id: UUID,
    payload: BulkReviewRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
):
    """One sign-off over all existing Simplify/Expand rewrites; no generation."""
    lesson, actor = await _lesson_for_review(session, principal, lesson_id)
    return await _bulk_approve(session, lesson, actor, payload, "rewrites")


@router.put(
    "/lessons/{lesson_id}/segments/{segment_id}/key-point",
    response_model=LessonReviewResponse,
    responses={409: {"description": "key_point_already_exists"}},
)
async def resolve_missing_key_point(
    lesson_id: UUID,
    segment_id: UUID,
    payload: MissingKeyPointWrite,
    principal: PrincipalDependency,
    session: DatabaseSession,
):
    """Persist an authored point or an explicit omission where extraction found none."""
    lesson, actor = await _lesson_for_review(session, principal, lesson_id)
    segment = await session.get(LessonSegment, segment_id)
    if not segment or segment.lesson_id != lesson.id:
        raise HTTPException(404, detail="Segment not found")
    points = list(
        await session.scalars(select(LessonKeyPoint).where(LessonKeyPoint.segment_id == segment.id))
    )
    if any(point.extracted_text for point in points):
        raise HTTPException(
            409,
            detail={
                "code": "key_point_already_exists",
                "message": "Edit the existing key point instead.",
            },
        )
    point = (
        points[0]
        if points
        else LessonKeyPoint(
            lesson_id=lesson.id,
            segment_id=segment.id,
            position=0,
            extracted_text="",
            source_text=segment.body,
            confidence=KeyPointConfidence.LOW,
        )
    )
    if (
        not points
        or point.text != (payload.text or "")
        or (point.review_state == KeyPointReviewState.REMOVED) != (payload.action == "omit")
    ):
        await _invalidate_signoffs(session, lesson.id, "key_points")
    point.amended_text = payload.text if payload.action == "add" else None
    _resolve(
        point,
        state=KeyPointReviewState.AMENDED
        if payload.action == "add"
        else KeyPointReviewState.REMOVED,
        actor=actor,
    )
    session.add(point)
    await _write_through(session, point)
    await session.commit()
    return await _review_result(session, lesson)


@router.patch(
    "/lessons/{lesson_id}/segments/{segment_id}/rewrites/{variant}",
    response_model=LessonReviewResponse,
)
async def edit_rewrite(
    lesson_id: UUID,
    segment_id: UUID,
    variant: Literal["simplified", "expanded"],
    payload: RewriteEdit,
    principal: PrincipalDependency,
    session: DatabaseSession,
):
    """Save wording as pending; only the lesson-wide act approves it."""
    lesson, actor = await _lesson_for_review(session, principal, lesson_id)
    segment = await session.get(LessonSegment, segment_id)
    if not segment or segment.lesson_id != lesson.id:
        raise HTTPException(404, detail="Segment not found")
    variants = dict(segment.depth_variants or {})
    original = variants.get(variant)
    if not isinstance(original, dict) or not original.get("body"):
        raise HTTPException(404, detail="Rewrite not found")
    if original["body"] != payload.body:
        await _invalidate_signoffs(session, lesson.id, "rewrites")
        changed = {
            **original,
            "originalBody": original.get("originalBody", original["body"]),
            "body": payload.body,
            "reviewStatus": "pending",
            "reviewedBy": None,
            "reviewedAt": None,
            "reviewedByName": None,
            "editedBy": str(actor.id),
            "editedAt": datetime.now(UTC).isoformat(),
        }
        variants[variant] = changed
        segment.depth_variants = variants
        await session.commit()
    return await _review_result(session, lesson)


async def outstanding_key_points(
    session: AsyncSession,
    lesson_ids: list[UUID],
) -> dict[UUID, int]:
    """How many points each lesson is still waiting on.

    Shared with the assignment gate, so "ready" means the same thing to the
    screen that counts down and to the endpoint that refuses.
    """

    if not lesson_ids:
        return {}
    rows = await session.execute(
        select(LessonKeyPoint.lesson_id, func.count(LessonKeyPoint.id))
        .where(
            LessonKeyPoint.lesson_id.in_(lesson_ids),
            LessonKeyPoint.review_state == KeyPointReviewState.UNSURE,
        )
        .group_by(LessonKeyPoint.lesson_id)
    )
    return dict(rows.all())  # type: ignore[arg-type]
