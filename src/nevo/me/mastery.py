"""A /me learner's own mastery and progress, in three levels and no numbers.

/me Phase 5. A port of the Learning Support view scoped to one learner: the
computation is the engine's, this only reads it and names it.

No score, no percentage, no grade, no numbered bar. A concept is reported as
the highest level the learner has reached, in order, and the next one they
are working towards, over the same per-level states the school screens read
(nevo.mastery.read, S21): a view, not a second model.

Progress across time is the moments a level was strengthened. The first paid
tier sees a rolling window; the second sees the full history; the free tier
is told progress exists and what unlocks it (a 200, not a 403: a product
state, not a fault).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.content_parsing.concept_names import readable_concept_name
from nevo.db.models.account import User
from nevo.db.models.frontend_support import Concept
from nevo.db.models.mastery import StudentConceptLevelMastery
from nevo.intelligence.learner_scope import learner_concepts
from nevo.mastery import read
from nevo.me import tiers

Level = read.Level
LEVELS = read.LEVELS

#: How far back the first paid tier sees. Not set by any ruling yet - the
#: plan says "a rolling window" without a length. Lydia's to confirm.
ROLLING_WINDOW = timedelta(days=90)


@dataclass(frozen=True)
class ConceptLevel:
    concept_id: object
    concept_name: str
    reached: Level | None
    working_towards: Level | None
    #: All three, for a learner who asks: only the levels observed.
    levels: dict = field(default_factory=dict)


@dataclass(frozen=True)
class LevelReached:
    concept_id: object
    concept_name: str
    level: Level
    reached_at: datetime


@dataclass(frozen=True)
class Progress:
    locked: bool
    unlocks_with: str | None = None
    window: Literal["rolling", "full"] | None = None
    since: datetime | None = None
    events: tuple[LevelReached, ...] = ()


async def _level_rows(session: AsyncSession, learner: User):
    return (
        await session.execute(
            select(StudentConceptLevelMastery, Concept)
            .join(Concept, Concept.id == StudentConceptLevelMastery.concept_id)
            .where(
                StudentConceptLevelMastery.student_id == learner.id,
                learner_concepts(learner),
            )
        )
    ).all()


async def concept_levels(session: AsyncSession, learner: User) -> list[ConceptLevel]:
    return [
        ConceptLevel(
            concept_id=item.concept_id,
            concept_name=item.concept_name,
            reached=item.reached,
            working_towards=item.working_towards,
            levels=dict(item.levels),
        )
        for item in await read.read_learner(session, learner.id, concepts=learner_concepts(learner))
        if item.levels
    ]


async def progress_for(
    session: AsyncSession, learner: User, tier: tiers.Tier, now: datetime | None = None
) -> Progress:
    now = now or datetime.now(UTC)
    if tier == tiers.FREE:
        return Progress(locked=True, unlocks_with=tiers.TWELVE.key)
    full = tier == tiers.TOP
    since = None if full else now - ROLLING_WINDOW
    events = [
        LevelReached(
            concept_id=concept.id,
            concept_name=readable_concept_name(concept.name),
            level=read.level_from_engine(row.mastery_level),
            reached_at=row.strengthened_at,
        )
        for row, concept in await _level_rows(session, learner)
        if row.strengthened_at is not None and (since is None or row.strengthened_at >= since)
    ]
    events.sort(key=lambda item: item.reached_at, reverse=True)
    return Progress(
        locked=False,
        window="full" if full else "rolling",
        since=since,
        events=tuple(events),
    )
