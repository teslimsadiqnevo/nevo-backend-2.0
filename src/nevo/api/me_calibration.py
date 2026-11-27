"""/me Phase 6: calibration, the waitlist and the enquiry.

Calibration routes are a learner's own (individual accounts only, by the
/api/v1/me prefix). The waitlist and the enquiry take no session: they are
reached before an account exists, or by a school or tutorial centre that
will never have a /me one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from nevo.api.auth import PrincipalDependency
from nevo.api.casing import CAMEL_CONFIG
from nevo.api.dependencies import DatabaseSession
from nevo.api.response_models import CamelResponse
from nevo.db.models.account import User
from nevo.db.models.content import Lesson
from nevo.db.models.me import MeCheckPrediction
from nevo.mastery import read
from nevo.me import calibration, contact

router = APIRouter(prefix="/api/v1", tags=["me"])

#: The names a learner reads (S21). The engine's own names are still taken
#: on the way in, so a client mid-switch is not refused.
Level = Literal["knowing_and_understanding", "application", "analysis_and_evaluation"]
_TO_ENGINE = {
    "knowing_and_understanding": "knowledge",
    "application": "application",
    "analysis_and_evaluation": "analysis",
    "knowledge": "knowledge",
    "analysis": "analysis",
}


class PredictionRequest(BaseModel):
    model_config = CAMEL_CONFIG

    level: Literal[
        "knowing_and_understanding",
        "application",
        "analysis_and_evaluation",
        "knowledge",
        "analysis",
    ]


class CalibrationResponse(CamelResponse):
    lesson_id: UUID
    predicted: Level
    predicted_at: datetime
    #: The highest level answered correctly since predicting. Omitted until
    #: then, and when the learner answered and reached none.
    reached: Level | None = None
    answered: bool
    #: matched, or over/under by levels. Omitted until there is an outcome.
    gap: calibration.Gap | None = None


class CalibrationHistoryResponse(CamelResponse):
    checks: list[CalibrationResponse]


class Accepted(CamelResponse):
    status: Literal["accepted"] = "accepted"


class WaitlistRequest(BaseModel):
    model_config = CAMEL_CONFIG

    email: EmailStr
    note: Annotated[str, Field(max_length=2000)] | None = None


class EnquiryRequest(BaseModel):
    model_config = CAMEL_CONFIG

    email: EmailStr
    name: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    who: Literal["learner", "lesson_teacher", "tutorial_centre", "school", "other"]
    note: Annotated[str, Field(max_length=2000)] | None = None


def _response(item: calibration.Calibration) -> CalibrationResponse:
    return CalibrationResponse(
        lesson_id=item.lesson_id,
        predicted=read.level_from_engine(item.predicted),
        predicted_at=item.predicted_at,
        reached=read.level_from_engine(item.reached) if item.reached else None,
        answered=item.answered,
        gap=item.gap,
    )


async def _own_lesson(session: DatabaseSession, principal, lesson_id: UUID) -> User:
    learner = await session.get(User, principal.user_id)
    lesson = await session.get(Lesson, lesson_id)
    if (
        learner is None
        or lesson is None
        or lesson.created_by_user_id != learner.id
        or lesson.school_id is not None
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "lesson_not_found"})
    return learner


@router.post(
    "/me/checks/{lesson_id}/prediction",
    response_model=CalibrationResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
)
async def predict(
    lesson_id: UUID,
    payload: PredictionRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> CalibrationResponse:
    """Before a lesson's check: the level the learner expects to reach.

    A new prediction starts a new comparison; attempts after it are judged
    against it, not against an earlier one.
    """

    learner = await _own_lesson(session, principal, lesson_id)
    session.add(
        MeCheckPrediction(
            learner_id=learner.id,
            lesson_id=lesson_id,
            predicted_level=_TO_ENGINE[payload.level],
            predicted_at=datetime.now(UTC),
        )
    )
    await session.commit()
    latest = await calibration.latest_for_lesson(session, learner.id, lesson_id)
    assert latest is not None
    return _response(latest)


@router.get(
    "/me/checks/{lesson_id}/prediction",
    response_model=CalibrationResponse,
    response_model_exclude_none=True,
)
async def prediction_outcome(
    lesson_id: UUID, principal: PrincipalDependency, session: DatabaseSession
) -> CalibrationResponse:
    """The latest prediction for this lesson's check, with the gap once answered."""

    learner = await _own_lesson(session, principal, lesson_id)
    latest = await calibration.latest_for_lesson(session, learner.id, lesson_id)
    if latest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "no_prediction"})
    return _response(latest)


@router.get(
    "/me/calibration",
    response_model=CalibrationHistoryResponse,
    response_model_exclude_none=True,
)
async def calibration_history(
    principal: PrincipalDependency, session: DatabaseSession
) -> CalibrationHistoryResponse:
    """Predictions against outcomes over time, newest first."""

    return CalibrationHistoryResponse(
        checks=[_response(item) for item in await calibration.history(session, principal.user_id)]
    )


@router.post("/me/waitlist", response_model=Accepted, status_code=status.HTTP_202_ACCEPTED)
async def join_waitlist(
    payload: WaitlistRequest, session: DatabaseSession, request: Request
) -> Accepted:
    saved = await contact.record(
        session, kind="waitlist", email=str(payload.email), note=payload.note
    )
    if saved is not None:
        await contact.alert_team(getattr(request.app.state, "email_delivery", None), saved)
    return Accepted()


@router.post("/me/enquiry", response_model=Accepted, status_code=status.HTTP_202_ACCEPTED)
async def enquire(payload: EnquiryRequest, session: DatabaseSession, request: Request) -> Accepted:
    """More than twenty-five lessons, or a teacher, tutorial centre or school.

    Routes to a person, never to a fourth price.
    """

    saved = await contact.record(
        session,
        kind="enquiry",
        email=str(payload.email),
        name=payload.name,
        who=payload.who,
        note=payload.note,
    )
    if saved is not None:
        await contact.alert_team(getattr(request.app.state, "email_delivery", None), saved)
    return Accepted()
