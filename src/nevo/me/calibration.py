"""Calibration: what a learner expected to reach in a check, against what they did.

/me Phase 6, ruling D1. University students are systematically
overconfident about what they know, and the weakest are the most
overconfident. The gap is useful to the learner and a signal the engine
cannot get from answers alone.

Expressed in levels, never scores. The outcome is the highest level the
learner answered a check question at correctly, in the attempts made after
the prediction and before the next one. The gap is a word: matched, or over
or under by one or two levels (over means they expected more than they
reached - the overconfident direction).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.db.models.me import MeCheckPrediction
from nevo.db.models.product import LessonQuestionAttempt

Level = Literal["knowledge", "application", "analysis"]
LEVELS: tuple[Level, ...] = ("knowledge", "application", "analysis")
Gap = Literal[
    "matched", "over_by_one", "over_by_two", "over_by_three", "under_by_one", "under_by_two"
]

_GAP: dict[int, Gap] = {
    0: "matched",
    1: "over_by_one",
    2: "over_by_two",
    #: Expected analysis and reached no level at all.
    3: "over_by_three",
    -1: "under_by_one",
    -2: "under_by_two",
}


@dataclass(frozen=True)
class Calibration:
    lesson_id: UUID
    predicted: Level
    predicted_at: datetime
    #: None until the learner has answered a check question since predicting,
    #: or when they answered and reached no level ("none_yet" on the wire).
    reached: Level | None
    answered: bool
    gap: Gap | None


def gap_between(predicted: Level, reached: Level | None) -> Gap | None:
    if reached is None:
        return None
    return _GAP[LEVELS.index(predicted) - LEVELS.index(reached)]


async def _outcome(
    session: AsyncSession, prediction: MeCheckPrediction, until: datetime | None
) -> tuple[bool, Level | None]:
    query = select(LessonQuestionAttempt).where(
        LessonQuestionAttempt.student_id == prediction.learner_id,
        LessonQuestionAttempt.lesson_id == prediction.lesson_id,
        LessonQuestionAttempt.submitted_at >= prediction.predicted_at,
    )
    if until is not None:
        query = query.where(LessonQuestionAttempt.submitted_at < until)
    attempts = list(await session.scalars(query))
    levelled = [
        attempt
        for attempt in attempts
        if (attempt.question_snapshot or {}).get("masteryLevel") in LEVELS
    ]
    reached = [
        LEVELS.index(attempt.question_snapshot["masteryLevel"])
        for attempt in levelled
        if attempt.correct
    ]
    return bool(levelled), (LEVELS[max(reached)] if reached else None)


async def _calibrate(
    session: AsyncSession, prediction: MeCheckPrediction, until: datetime | None
) -> Calibration:
    answered, reached = await _outcome(session, prediction, until)
    return Calibration(
        lesson_id=prediction.lesson_id,
        predicted=prediction.predicted_level,
        predicted_at=prediction.predicted_at,
        reached=reached,
        answered=answered,
        # A learner who answered and reached nothing predicted above even the
        # first level: that is a gap too, counted from below knowledge.
        gap=(
            gap_between(prediction.predicted_level, reached)
            if reached is not None
            else (
                _GAP.get(LEVELS.index(prediction.predicted_level) + 1)
                if answered
                else None
            )
        ),
    )


async def history(session: AsyncSession, learner_id: UUID, limit: int = 50) -> list[Calibration]:
    """Every prediction, newest first, each judged against its own attempts."""

    predictions = list(
        await session.scalars(
            select(MeCheckPrediction)
            .where(MeCheckPrediction.learner_id == learner_id)
            .order_by(MeCheckPrediction.lesson_id, MeCheckPrediction.predicted_at)
        )
    )
    results = []
    for index, prediction in enumerate(predictions):
        following = predictions[index + 1] if index + 1 < len(predictions) else None
        until = (
            following.predicted_at
            if following is not None and following.lesson_id == prediction.lesson_id
            else None
        )
        results.append(await _calibrate(session, prediction, until))
    results.sort(key=lambda item: item.predicted_at, reverse=True)
    return results[:limit]


async def latest_for_lesson(
    session: AsyncSession, learner_id: UUID, lesson_id: UUID
) -> Calibration | None:
    prediction = await session.scalar(
        select(MeCheckPrediction)
        .where(
            MeCheckPrediction.learner_id == learner_id,
            MeCheckPrediction.lesson_id == lesson_id,
        )
        .order_by(MeCheckPrediction.predicted_at.desc())
        .limit(1)
    )
    return await _calibrate(session, prediction, None) if prediction else None
