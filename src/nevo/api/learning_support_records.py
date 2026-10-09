"""What Nevo did for a child, dated, and who wrote what on the document.

Two things the learning support surface asked for and could not have.

A member of staff writes notes before the document is produced, and those
notes are the school's rather than Nevo's. They are stored as rows with a
named author and a time, and every passage the document renders says which of
the two wrote it, so a parent reading it is never unsure - and neither is a
regulator reading it afterwards.

And accommodations were inferred fresh every time anyone asked, so the surface
could say what is true today and never what changed in March or why. A change
is now a dated row. Both records are about the software: what it did, never
what the child is. There is no score, index, rating or forecast here.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.api.auth import PrincipalDependency
from nevo.api.casing import CAMEL_CONFIG
from nevo.api.dependencies import DatabaseSession
from nevo.api.learning_support import require_learning_support_if_admin
from nevo.api.product_common import can_access_student, require_school_actor
from nevo.api.response_models import CamelResponse
from nevo.db.models.account import User
from nevo.db.models.export import IepExport
from nevo.db.models.learner_profile import LearnerProfileHistory
from nevo.db.models.learning_support import AccommodationChange, ExportAnnotation
from nevo.db.models.signal_event import SignalEvent
from nevo.domain.intelligence.vocabulary import AccommodationType
from nevo.domain.learning_support.vocabulary import (
    AccommodationChangeAction,
    AnnotationOrigin,
)
from nevo.domain.signal_events.vocabulary import SignalEventType

router = APIRouter(prefix="/api/v1", tags=["learning support"])

STAFF_ROLES = {"teacher", "senco_admin", "other_admin"}

#: The events that are Nevo adapting a lesson to a learner. Counted weekly and
#: unsmoothed: a rolling average hides the week something changed, which is
#: the only week anybody is looking for.
ADAPTATION_EVENTS = (
    SignalEventType.SIMPLIFY_TRIGGER,
    SignalEventType.EXPAND_TRIGGER,
    SignalEventType.SLOWER_TRIGGER,
    SignalEventType.MODALITY_SUGGESTION_SHOWN,
    SignalEventType.MODALITY_SUGGESTION_ACCEPTED,
    SignalEventType.MODALITY_MANUAL_SWITCH,
    SignalEventType.BREAK_SUGGESTED,
)

MAX_WEEKS = 52


class AnnotationWrite(BaseModel):
    """What a member of staff sends. The author and the time are not theirs
    to state, so they are not in this shape."""

    model_config = CAMEL_CONFIG

    body: Annotated[str, Field(min_length=1, max_length=4000)]


class AnnotationResponse(CamelResponse):
    id: UUID
    export_id: UUID
    body: str
    author_user_id: UUID
    #: As it stood when they wrote it, so a shared document still names the
    #: author after they have left the school.
    author_name: str
    author_role: str
    created_at: datetime
    #: Always school_staff on these rows. Stated rather than implied, because
    #: the whole point is that a reader can tell them from Nevo's own text.
    origin: AnnotationOrigin = AnnotationOrigin.SCHOOL_STAFF


class ExportComposition(CamelResponse):
    """The document, in blocks that each say who wrote them."""

    export_id: UUID
    student_id: UUID
    #: draft or final. A document cannot be shared with a parent before it is
    #: final, which the share endpoint already enforces.
    status: str
    nevo_text: str
    annotations: list[AnnotationResponse]
    #: The note whoever approved the document left, kept apart from the staff
    #: annotations because approving and annotating are different acts.
    review_note: str | None
    reviewed_by: UUID | None
    reviewed_at: datetime | None


class AccommodationChangeResponse(CamelResponse):
    accommodation: AccommodationType
    action: AccommodationChangeAction
    #: What Nevo saw. Never a description of the child.
    prompted_by: str
    observed_over_lessons: int | None
    occurred_at: datetime


class WeeklyCount(CamelResponse):
    #: The Monday of the week, so a client can label it without guessing.
    week_starting: date
    count: int


class DimensionPoint(CamelResponse):
    recorded_at: datetime
    #: The stored value as it was, not a rating derived from it.
    value: str | None
    confidence: str


class DimensionSeries(CamelResponse):
    dimension: str
    points: list[DimensionPoint]


class AccommodationHistory(CamelResponse):
    """A dated record of what Nevo did, and nothing about the learner."""

    student_id: UUID
    changes: list[AccommodationChangeResponse]
    #: Unsmoothed and with no projection: the weeks are the weeks.
    adaptations_per_week: list[WeeklyCount]
    series: list[DimensionSeries]


class StudentAccommodationSummary(CamelResponse):
    student_id: UUID
    student_name: str
    active: list[AccommodationType]
    last_changed_at: datetime | None


@router.get(
    "/accommodations",
    response_model=list[StudentAccommodationSummary],
)
async def list_active_accommodations(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> list[StudentAccommodationSummary]:
    """Current inferred delivery adjustments across the caller's school."""
    actor = await require_school_actor(session, principal, roles=STAFF_ROLES)
    await require_learning_support_if_admin(session, actor)
    students = list(
        await session.scalars(
            select(User)
            .where(User.school_id == actor.school_id, User.role == "student")
            .order_by(User.first_name, User.last_name)
        )
    )
    if not students:
        return []
    changes = list(
        await session.scalars(
            select(AccommodationChange)
            .where(AccommodationChange.student_id.in_([student.id for student in students]))
            .order_by(AccommodationChange.occurred_at.desc())
        )
    )
    latest: dict[tuple[UUID, AccommodationType], AccommodationChange] = {}
    for change in changes:
        latest.setdefault((change.student_id, change.accommodation), change)
    return [
        StudentAccommodationSummary(
            student_id=student.id,
            student_name=" ".join(
                part for part in (student.first_name, student.last_name) if part
            )
            or "Student",
            active=sorted(
                [
                    accommodation
                    for (student_id, accommodation), change in latest.items()
                    if student_id == student.id
                    and change.action is AccommodationChangeAction.ADDED
                ],
                key=lambda item: item.value,
            ),
            last_changed_at=max(
                (
                    change.occurred_at
                    for (student_id, _), change in latest.items()
                    if student_id == student.id
                ),
                default=None,
            ),
        )
        for student in students
    ]


async def _student(session: AsyncSession, actor: User, student_id: UUID) -> User:
    if not await can_access_student(session, actor, student_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    student = await session.get(User, student_id)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    return student


async def _export(session: AsyncSession, actor: User, export_id: UUID) -> IepExport:
    export = await session.get(IepExport, export_id)
    if export is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export not found")
    await _student(session, actor, export.student_id)
    return export


def _annotation(row: ExportAnnotation) -> AnnotationResponse:
    return AnnotationResponse(
        id=row.id,
        export_id=row.export_id,
        body=row.body,
        author_user_id=row.author_user_id,
        author_name=row.author_name,
        author_role=row.author_role,
        created_at=row.created_at,
    )


@router.post(
    "/exports/iep/{export_id}/annotations",
    response_model=AnnotationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_annotation(
    export_id: UUID,
    payload: AnnotationWrite,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> AnnotationResponse:
    """A member of staff adds their own note to a child's document.

    The author and the timestamp are stamped here rather than accepted from
    the client: a note on a child's record that says whatever the caller
    claimed about who wrote it is not a record of anything.
    """

    actor = await require_school_actor(session, principal, roles=STAFF_ROLES)
    export = await _export(session, actor, export_id)
    if export.status.value == "final":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "export_already_final",
                "message": (
                    "This document has been approved. Annotations belong to the "
                    "draft; produce a new one to add to it."
                ),
            },
        )
    row = ExportAnnotation(
        export_id=export_id,
        student_id=export.student_id,
        author_user_id=actor.id,
        author_name=" ".join(part for part in (actor.first_name, actor.last_name) if part),
        author_role=actor.role.value,
        body=payload.body.strip(),
        created_at=datetime.now(UTC),
    )
    session.add(row)
    await session.commit()
    return _annotation(row)


@router.get("/exports/iep/{export_id}/composition", response_model=ExportComposition)
async def read_composition(
    export_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> ExportComposition:
    """The document split by who wrote each part.

    One read, so a renderer never has to decide for itself which words came
    from where - which is how a parent ends up unsure whether their school or
    a piece of software said something about their child.
    """

    actor = await require_school_actor(session, principal, roles=STAFF_ROLES)
    export = await _export(session, actor, export_id)
    rows = await session.scalars(
        select(ExportAnnotation)
        .where(ExportAnnotation.export_id == export_id)
        .order_by(ExportAnnotation.created_at)
    )
    return ExportComposition(
        export_id=export_id,
        student_id=export.student_id,
        status=export.status.value,
        nevo_text=export.export_content,
        annotations=[_annotation(row) for row in rows],
        review_note=export.review_note,
        reviewed_by=export.reviewed_by_user_id,
        reviewed_at=export.reviewed_at,
    )


@router.get(
    "/students/{student_id}/accommodation-history",
    response_model=AccommodationHistory,
)
async def read_accommodation_history(
    student_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
    weeks: Annotated[int, Field(ge=1, le=MAX_WEEKS)] = 12,
) -> AccommodationHistory:
    """A dated record of what Nevo did for this child.

    Not a score over time. Every figure here is a count of the software's own
    actions or a value it already stores, and the weekly counts are raw: a
    smoothed line hides the week something changed, and the week something
    changed is the only week anybody opens this for.
    """

    actor = await require_school_actor(session, principal, roles=STAFF_ROLES)
    await _student(session, actor, student_id)
    await require_learning_support_if_admin(session, actor)
    since = datetime.now(UTC) - timedelta(weeks=weeks)
    changes = await session.scalars(
        select(AccommodationChange)
        .where(
            AccommodationChange.student_id == student_id,
            AccommodationChange.occurred_at >= since,
        )
        .order_by(AccommodationChange.occurred_at.desc())
    )
    weekly = await session.execute(
        select(
            func.date_trunc("week", SignalEvent.timestamp).label("week"),
            func.count(SignalEvent.id),
        )
        .where(
            SignalEvent.student_id == student_id,
            SignalEvent.timestamp >= since,
            SignalEvent.event_type.in_(list(ADAPTATION_EVENTS)),
        )
        .group_by("week")
        .order_by("week")
    )
    history = await session.scalars(
        select(LearnerProfileHistory)
        .where(
            LearnerProfileHistory.learner_id == student_id,
            LearnerProfileHistory.created_at >= since,
        )
        .order_by(LearnerProfileHistory.created_at)
    )
    return AccommodationHistory(
        student_id=student_id,
        changes=[
            AccommodationChangeResponse(
                accommodation=row.accommodation,
                action=row.action,
                prompted_by=row.prompted_by,
                observed_over_lessons=row.observed_over_lessons,
                occurred_at=row.occurred_at,
            )
            for row in changes
        ],
        adaptations_per_week=[
            WeeklyCount(week_starting=week.date(), count=int(count)) for week, count in weekly.all()
        ],
        series=_series(list(history)),
    )


#: The two dimensions the surface draws as a pair, so a reader can see when
#: the gap between them widened or closed. Stored values, not derived ones.
SERIES_DIMENSIONS = (
    ("conceptUnderstanding", "visual_spatial_preference"),
    ("readingDemand", "reading_writing_preference"),
)


def _series(history: list[LearnerProfileHistory]) -> list[DimensionSeries]:
    series = []
    for label, column in SERIES_DIMENSIONS:
        points = []
        for row in history:
            value = getattr(row, column, None)
            confidence = getattr(row, f"{column}_confidence", None)
            points.append(
                DimensionPoint(
                    recorded_at=row.created_at,
                    value=value.value if value is not None else None,
                    confidence=confidence.value if confidence is not None else "unknown",
                )
            )
        series.append(DimensionSeries(dimension=label, points=points))
    return series


async def record_accommodation_changes(
    session: AsyncSession,
    *,
    student_id: UUID,
    active: set[AccommodationType],
    prompted_by: dict[AccommodationType, str],
    observed_over_lessons: int | None = None,
) -> list[AccommodationChange]:
    """Write down what changed since the last time we looked.

    Called where accommodations are worked out, so the log is a record of
    Nevo's decisions rather than of somebody happening to open a screen. A
    set that has not changed writes nothing.
    """

    previous = await _current_accommodations(session, student_id)
    now = datetime.now(UTC)
    written = []
    for accommodation in sorted(active - previous, key=lambda item: item.value):
        written.append(
            AccommodationChange(
                student_id=student_id,
                accommodation=accommodation,
                action=AccommodationChangeAction.ADDED,
                prompted_by=prompted_by.get(accommodation, "observed_pattern"),
                observed_over_lessons=observed_over_lessons,
                occurred_at=now,
            )
        )
    for accommodation in sorted(previous - active, key=lambda item: item.value):
        written.append(
            AccommodationChange(
                student_id=student_id,
                accommodation=accommodation,
                action=AccommodationChangeAction.REMOVED,
                prompted_by=prompted_by.get(accommodation, "pattern_no_longer_seen"),
                observed_over_lessons=observed_over_lessons,
                occurred_at=now,
            )
        )
    for row in written:
        session.add(row)
    return written


async def _current_accommodations(
    session: AsyncSession,
    student_id: UUID,
) -> set[AccommodationType]:
    """What is in force now, read back from the log itself.

    The log is the record, so it is also the source: holding the current set
    somewhere else would give two answers that can disagree.
    """

    rows = await session.execute(
        select(
            AccommodationChange.accommodation,
            AccommodationChange.action,
            func.row_number()
            .over(
                partition_by=AccommodationChange.accommodation,
                order_by=AccommodationChange.occurred_at.desc(),
            )
            .label("recency"),
        ).where(AccommodationChange.student_id == student_id)
    )
    return {
        accommodation
        for accommodation, action, recency in rows.all()
        if recency == 1 and action is AccommodationChangeAction.ADDED
    }
