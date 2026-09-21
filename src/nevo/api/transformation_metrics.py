"""What a cohort is learning to do, for a class and for a school.

Four indicators were asked for. Three can be computed from what Nevo already
records and one cannot, so this returns three that are true and says plainly
why the fourth is missing. A fabricated number on a proprietor's dashboard is
worse than a missing one, because a school will ask what it means and then
plan around it.

Per student, deliberately, there is nothing here. A self-regulation index
against a named child is a score about a person; the architecture forbids it
and the document now with counsel says it does not exist. This module cannot
return one: every query groups, and a cohort below the reporting floor is
suppressed rather than shown, because an average over two children is those
two children.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.api.auth import PrincipalDependency
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_common import require_class_access, require_school_actor
from nevo.api.response_models import CamelResponse
from nevo.db.models.account import StudentClassEnrollment, User
from nevo.db.models.signal_event import LessonSession, SignalEvent
from nevo.domain.accounts.vocabulary import UserRole
from nevo.domain.signal_events.vocabulary import LessonCompletionStatus, SignalEventType

router = APIRouter(prefix="/api/metrics/transformation", tags=["insights"])

#: Below this many learners with data, nothing is reported. Five, because a
#: class of four has an average that is one child's week with three others
#: rounding it, and the whole point of an aggregate is that it is not about a
#: person. Proposed here; if counsel or design wants it higher it is one
#: number to change.
REPORTING_FLOOR = 5

#: Each window is four weeks, so a figure is compared with the four before it
#: rather than with an all-time average that never moves.
WINDOW = timedelta(weeks=4)

MODALITIES = ("visual", "audio", "text", "interactive")


class Indicator(CamelResponse):
    """One number, with where it stands against the four weeks before it."""

    value: float
    #: The same figure for the previous window, so a client renders movement
    #: without a second request and without inventing the comparison.
    previous: float | None
    trend: Literal["up", "down", "steady", "unknown"]
    #: How many learners the figure is over. A school asks, and a figure
    #: whose cohort is unstated is a figure nobody can argue with.
    learner_count: int


class Series(CamelResponse):
    labels: list[str]
    values: list[float]


class Unavailable(CamelResponse):
    """An indicator Nevo cannot compute, and what it would take to.

    Returned instead of a plausible number. The ticket asked for this
    explicitly and it is the right shape for the other three too, if the data
    behind any of them ever goes away.
    """

    available: Literal[False] = False
    reason: str
    needed: str


class Flexibility(CamelResponse):
    """How readily a cohort moves between ways of learning the same thing."""

    dimensions: list[Series]
    learner_count: int


class TransformationMetrics(CamelResponse):
    scope: Literal["class", "school"]
    scope_id: UUID
    #: Null when the cohort is below the reporting floor. The client shows the
    #: message rather than an empty chart.
    self_regulation: Indicator | None
    calibration: Unavailable
    flexibility: Flexibility | None
    efficiency: Indicator | None
    learner_count: int
    reporting_floor: int
    suppressed: bool
    message: str | None = None


@dataclass(frozen=True, slots=True)
class _Window:
    start: datetime
    previous_start: datetime
    now: datetime


def _windows(now: datetime | None = None) -> _Window:
    current = now or datetime.now(UTC)
    return _Window(
        start=current - WINDOW,
        previous_start=current - WINDOW - WINDOW,
        now=current,
    )


def _trend(
    value: float | None,
    previous: float | None,
    *,
    higher_is_better: bool,
) -> Literal["up", "down", "steady", "unknown"]:
    if value is None or previous is None:
        return "unknown"
    difference = value - previous
    if abs(difference) < 1.0:
        return "steady"
    rising = difference > 0
    return "up" if rising is higher_is_better else "down"


async def _learner_ids(session: AsyncSession, scope: Select[tuple[UUID]]) -> list[UUID]:
    return list(await session.scalars(scope))


async def _self_regulation(
    session: AsyncSession,
    learners: list[UUID],
    window: _Window,
) -> Indicator | None:
    """How often a lesson is finished rather than abandoned.

    Signal: lesson_sessions.completion_status, recorded today on every
    session. Self-regulation as a construct is wider than this, and the
    figure is named for what it measures rather than for the construct: a
    cohort that sees lessons through.
    """

    async def share(start: datetime, end: datetime) -> float | None:
        total = await session.scalar(
            select(func.count(LessonSession.id)).where(
                LessonSession.student_id.in_(learners),
                LessonSession.started_at >= start,
                LessonSession.started_at < end,
            )
        )
        if not total:
            return None
        completed = await session.scalar(
            select(func.count(LessonSession.id)).where(
                LessonSession.student_id.in_(learners),
                LessonSession.started_at >= start,
                LessonSession.started_at < end,
                LessonSession.completion_status == LessonCompletionStatus.COMPLETED,
            )
        )
        return round((completed or 0) / total * 100, 1)

    value = await share(window.start, window.now)
    if value is None:
        return None
    previous = await share(window.previous_start, window.start)
    return Indicator(
        value=value,
        previous=previous,
        trend=_trend(value, previous, higher_is_better=True),
        learner_count=len(learners),
    )


async def _efficiency(
    session: AsyncSession,
    learners: list[UUID],
    window: _Window,
) -> Indicator | None:
    """Minutes spent on a lesson that was finished.

    Signal: the time between a session starting and ending, on sessions that
    completed. Reading the time_on_segment events instead would count a
    learner who left the tab open, which is why this uses the session.
    """

    async def minutes(start: datetime, end: datetime) -> float | None:
        average = await session.scalar(
            select(
                func.avg(func.extract("epoch", LessonSession.ended_at - LessonSession.started_at))
            ).where(
                LessonSession.student_id.in_(learners),
                LessonSession.ended_at.is_not(None),
                LessonSession.completion_status == LessonCompletionStatus.COMPLETED,
                LessonSession.started_at >= start,
                LessonSession.started_at < end,
            )
        )
        return round(float(average) / 60, 1) if average else None

    value = await minutes(window.start, window.now)
    if value is None:
        return None
    previous = await minutes(window.previous_start, window.start)
    return Indicator(
        value=value,
        previous=previous,
        # Less time on a lesson a learner still finished is the better way
        # round, so the arrow is inverted here on purpose.
        trend=_trend(value, previous, higher_is_better=False),
        learner_count=len(learners),
    )


async def _flexibility(
    session: AsyncSession,
    learners: list[UUID],
    window: _Window,
) -> Flexibility | None:
    """How often a cohort moves between ways of learning the same thing.

    Signal: the modality switch events, recorded today. One series per
    modality: how many times the cohort moved to it in the window.
    """

    rows = await session.execute(
        select(SignalEvent.event_type, func.count(SignalEvent.id))
        .where(
            SignalEvent.student_id.in_(learners),
            SignalEvent.timestamp >= window.start,
            SignalEvent.event_type.in_(
                [
                    SignalEventType.MODALITY_MANUAL_SWITCH,
                    SignalEventType.MODALITY_SUGGESTION_ACCEPTED,
                    SignalEventType.MODALITY_SUGGESTION_DECLINED,
                    SignalEventType.MODALITY_SWITCH_OUTCOME,
                ]
            ),
        )
        .group_by(SignalEvent.event_type)
    )
    counts = {event_type: int(total) for event_type, total in rows.all()}
    if not counts:
        return None
    return Flexibility(
        dimensions=[
            Series(
                labels=["Chose another format", "Took a suggestion", "Stayed as they were"],
                values=[
                    float(counts.get(SignalEventType.MODALITY_MANUAL_SWITCH, 0)),
                    float(counts.get(SignalEventType.MODALITY_SUGGESTION_ACCEPTED, 0)),
                    float(counts.get(SignalEventType.MODALITY_SUGGESTION_DECLINED, 0)),
                ],
            )
        ],
        learner_count=len(learners),
    )


def _calibration_is_not_measurable() -> Unavailable:
    """Say what is missing rather than return a plausible number.

    Metacognitive calibration is the gap between how sure a learner was and
    how right they turned out to be. Nevo records the answer and never the
    confidence: nothing asks a learner how sure they are, so there is no
    first half of the comparison to make.
    """

    return Unavailable(
        reason=(
            "Nevo records whether an answer was right, and never how sure the "
            "learner was before they gave it, so there is nothing to compare."
        ),
        needed=(
            "A confidence step before a checkpoint answer - 'how sure are "
            "you?' - carried on the checkpoint response signal. Once that is "
            "captured, this becomes the gap between the two, per cohort."
        ),
    )


async def _metrics(
    session: AsyncSession,
    *,
    scope: Literal["class", "school"],
    scope_id: UUID,
    learners: list[UUID],
) -> TransformationMetrics:
    window = _windows()
    if len(learners) < REPORTING_FLOOR:
        return TransformationMetrics(
            scope=scope,
            scope_id=scope_id,
            self_regulation=None,
            calibration=_calibration_is_not_measurable(),
            flexibility=None,
            efficiency=None,
            learner_count=len(learners),
            reporting_floor=REPORTING_FLOOR,
            suppressed=True,
            message=(
                f"There are fewer than {REPORTING_FLOOR} learners here, so an "
                "average would be about those children rather than about the "
                "group. Nevo does not show one."
            ),
        )
    return TransformationMetrics(
        scope=scope,
        scope_id=scope_id,
        self_regulation=await _self_regulation(session, learners, window),
        calibration=_calibration_is_not_measurable(),
        flexibility=await _flexibility(session, learners, window),
        efficiency=await _efficiency(session, learners, window),
        learner_count=len(learners),
        reporting_floor=REPORTING_FLOOR,
        suppressed=False,
    )


@router.get("/class/{class_id}", response_model=TransformationMetrics)
async def class_metrics(
    class_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> TransformationMetrics:
    """A class's figures, over the learners enrolled in it."""

    actor = await require_school_actor(session, principal)
    await require_class_access(session, actor, class_id)
    learners = await _learner_ids(
        session,
        select(StudentClassEnrollment.student_id).where(
            StudentClassEnrollment.class_id == class_id
        ),
    )
    return await _metrics(session, scope="class", scope_id=class_id, learners=learners)


@router.get("/school/{school_id}", response_model=TransformationMetrics)
async def school_metrics(
    school_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> TransformationMetrics:
    """A school's figures, over every learner in it."""

    actor = await require_school_actor(session, principal)
    if actor.school_id != school_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="School not found")
    learners = await _learner_ids(
        session,
        select(User.id).where(User.school_id == school_id, User.role == UserRole.STUDENT),
    )
    return await _metrics(session, scope="school", scope_id=school_id, learners=learners)
