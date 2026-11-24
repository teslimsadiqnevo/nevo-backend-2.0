"""A /me learner's own mastery and progress, in three levels and no numbers.

/me Phase 5. A port of the Learning Support view scoped to one learner: the
computation is the engine's, this only reads it and names it.

No score, no percentage, no grade, no numbered bar. A concept is reported as
the highest of knowledge, application and analysis the learner has reached,
in order, and the next one they are working towards. Reached means what it
means to the engine when it chooses review work: probability at or above
MASTERY_THRESHOLD with LEVEL_INDEPENDENT_PASSES independent passes.

Progress across time is the moments a level was strengthened. The first paid
tier sees a rolling window; the second sees the full history; the free tier
is told progress exists and what unlocks it (a 200, not a 403: a product
state, not a fault).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.content_parsing.concept_names import readable_concept_name
from nevo.db.models.account import User
from nevo.db.models.frontend_support import Concept
from nevo.db.models.mastery import StudentConceptLevelMastery
from nevo.intelligence.learner_scope import learner_concepts
from nevo.intelligence.learning_runtime import MASTERY_THRESHOLD
from nevo.intelligence.progression import LEVEL_INDEPENDENT_PASSES
from nevo.me import tiers

Level = Literal["knowledge", "application", "analysis"]
LEVELS: tuple[Level, ...] = ("knowledge", "application", "analysis")

#: How far back the first paid tier sees. Not set by any ruling yet - the
#: plan says "a rolling window" without a length. Lydia's to confirm.
ROLLING_WINDOW = timedelta(days=90)


@dataclass(frozen=True)
class ConceptLevel:
    concept_id: object
    concept_name: str
    reached: Level | None
    working_towards: Level | None


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


def _reached(row: StudentConceptLevelMastery | None) -> bool:
    return (
        row is not None
        and row.mastery_probability >= MASTERY_THRESHOLD
        and row.independent_pass_count >= LEVEL_INDEPENDENT_PASSES
    )


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
    by_concept: dict[object, tuple[Concept, dict[str, StudentConceptLevelMastery]]] = {}
    for row, concept in await _level_rows(session, learner):
        by_concept.setdefault(concept.id, (concept, {}))[1][row.mastery_level] = row
    result = []
    for concept, rows in by_concept.values():
        reached: Level | None = None
        for level in LEVELS:
            if not _reached(rows.get(level)):
                break
            reached = level
        index = LEVELS.index(reached) + 1 if reached else 0
        result.append(
            ConceptLevel(
                concept_id=concept.id,
                concept_name=readable_concept_name(concept.name),
                reached=reached,
                working_towards=LEVELS[index] if index < len(LEVELS) else None,
            )
        )
    return sorted(result, key=lambda item: item.concept_name.casefold())


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
            level=row.mastery_level,
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
