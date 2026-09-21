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

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.api.auth import PrincipalDependency
from nevo.api.casing import CAMEL_CONFIG
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_common import require_school_actor
from nevo.api.response_models import CamelResponse
from nevo.db.models.account import User
from nevo.db.models.content import Lesson, LessonKeyPoint, LessonSegment
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
    lesson = await session.get(Lesson, lesson_id)
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
    return _review(lesson, await _key_point_rows(session, lesson_id))


@router.post(
    "/lessons/{lesson_id}/key-points/{key_point_id}/accept",
    response_model=LessonReviewResponse,
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
    return _review(lesson, await _key_point_rows(session, lesson_id))


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
    point.amended_text = payload.text.strip()
    _resolve(point, state=KeyPointReviewState.AMENDED, actor=actor)
    await _write_through(session, point)
    await session.commit()
    return _review(lesson, await _key_point_rows(session, lesson_id))


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
    _resolve(point, state=KeyPointReviewState.REMOVED, actor=actor)
    await _write_through(session, point)
    await session.commit()
    return _review(lesson, await _key_point_rows(session, lesson_id))


async def _write_through(session: AsyncSession, point: LessonKeyPoint) -> None:
    """Put the teacher's decision into the variant a child is served."""

    segment = await session.get(LessonSegment, point.segment_id)
    if segment is None or not isinstance(segment.text_variant, dict):
        return
    points = await session.scalars(
        select(LessonKeyPoint)
        .where(LessonKeyPoint.segment_id == point.segment_id)
        .order_by(LessonKeyPoint.position)
    )
    kept = [
        item.text for item in points if item.review_state is not KeyPointReviewState.REMOVED
    ]
    segment.text_variant = {**segment.text_variant, "keyPoints": kept}


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
