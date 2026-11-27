"""The mastery read: a state for each of the three levels, per learner, per concept.

S21, Lydia's engine specification of 26 November 2026, section 7. Four school
screens show mastery as two bars, understanding and reading, and hold that way
(the 9 November ruling) until the server holds per-level states. This is that
read. The screens switch to it together, in one release; the /me learner
view, which has no old model, takes it at once.

The three levels, named as the school proposal names them. The engine stores
the first as "knowledge"; nothing outside this module and the engine should
ever say so again:

    knowing_and_understanding, application, analysis_and_evaluation

Per level a learner is in one of three states, or in none:

    reached   the engine counts it as mastered - the same rule it uses to
              choose review work: probability at or above MASTERY_THRESHOLD
              with LEVEL_INDEPENDENT_PASSES passes without support.
    working   observed, at least one pass at this level, not yet reached.
    not       observed, and no pass at this level yet.
    (absent)  nothing observed at this level. Never guessed: an absent state
              and `not` are different facts and are drawn differently.

Reading is reported beside the levels and never as one. It says what the
material demands of the learner, not what they have mastered:

    at        reading is not what stands between them and the concept.
    support   reading is likely in the way: the engine's reading estimate is
              below its borderline, or it put their last miss down to the text.
    none      the concept has only been met in material that asks for very
              little reading, so there is nothing to say about it.
    (absent)  nothing observed.

The boundaries between working and not, and the meaning of reading `none`,
are this module's reading of the specification, which names the states and
not their edges. They are here and nowhere else, so a ruling changes one
place.

No score, no percentage and no probability leaves this module.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.content_parsing.concept_names import readable_concept_name
from nevo.db.models.frontend_support import Concept
from nevo.db.models.mastery import StudentConceptLevelMastery, StudentConceptMastery
from nevo.db.models.product import LessonQuestionAttempt
from nevo.domain.mastery.vocabulary import FailureAttribution
from nevo.intelligence.learning_runtime import MASTERY_THRESHOLD
from nevo.intelligence.progression import LEVEL_INDEPENDENT_PASSES
from nevo.mastery.engine import BORDERLINE_READING_THRESHOLD

Level = Literal["knowing_and_understanding", "application", "analysis_and_evaluation"]
LevelState = Literal["reached", "working", "not"]
ReadingState = Literal["at", "support", "none"]

#: In order: a learner works up through them.
LEVELS: tuple[Level, ...] = ("knowing_and_understanding", "application", "analysis_and_evaluation")

#: The engine's own names, which stay inside the engine and its tables.
_FROM_ENGINE: dict[str, Level] = {
    "knowledge": "knowing_and_understanding",
    "application": "application",
    "analysis": "analysis_and_evaluation",
}

#: Below this text density an item asks for very little reading (a sum, a
#: labelled diagram). Matches the engine's lightest weighting of reading.
TEXT_LIGHT = 0.2
#: What the engine assumes for a question that carries no density: heavy.
UNSTATED_DENSITY = 0.8


def level_from_engine(value: str) -> Level:
    return _FROM_ENGINE[value]


def level_state(row: StudentConceptLevelMastery | None) -> LevelState | None:
    if row is None or row.practice_count <= 0:
        return None
    if (
        row.mastery_probability >= MASTERY_THRESHOLD
        and row.independent_pass_count >= LEVEL_INDEPENDENT_PASSES
    ):
        return "reached"
    if row.independent_pass_count + row.supported_pass_count > 0:
        return "working"
    return "not"


def reading_state(
    row: StudentConceptMastery | None, *, max_text_density: float | None = None
) -> ReadingState | None:
    if row is None or row.practice_count <= 0:
        return None
    if max_text_density is not None and max_text_density < TEXT_LIGHT:
        return "none"
    if row.mastery_probability_reading < BORDERLINE_READING_THRESHOLD or (
        row.last_failure_attribution in {FailureAttribution.READING, FailureAttribution.MIXED}
    ):
        return "support"
    return "at"


def highest_reached(levels: dict[Level, LevelState]) -> Level | None:
    """The highest level reached in order: a gap stops the climb."""

    reached: Level | None = None
    for level in LEVELS:
        if levels.get(level) != "reached":
            break
        reached = level
    return reached


def next_level(reached: Level | None) -> Level | None:
    index = LEVELS.index(reached) + 1 if reached else 0
    return LEVELS[index] if index < len(LEVELS) else None


@dataclass(frozen=True)
class ConceptRead:
    concept_id: UUID
    concept_name: str
    #: Only the levels something was observed at.
    levels: dict[Level, LevelState] = field(default_factory=dict)
    reading: ReadingState | None = None

    @property
    def reached(self) -> Level | None:
        return highest_reached(self.levels)

    @property
    def working_towards(self) -> Level | None:
        return next_level(self.reached)


async def read_learner(
    session: AsyncSession, learner_id: UUID, *, concepts: ColumnElement[bool] | None = None
) -> list[ConceptRead]:
    """Every concept the learner has evidence on, with its level states."""

    level_query = (
        select(StudentConceptLevelMastery, Concept)
        .join(Concept, Concept.id == StudentConceptLevelMastery.concept_id)
        .where(StudentConceptLevelMastery.student_id == learner_id)
    )
    reading_query = select(StudentConceptMastery).where(
        StudentConceptMastery.student_id == learner_id
    )
    if concepts is not None:
        level_query = level_query.where(concepts)
        reading_query = reading_query.join(
            Concept, Concept.id == StudentConceptMastery.concept_id
        ).where(concepts)

    by_concept: dict[UUID, tuple[Concept, dict[Level, LevelState]]] = {}
    for row, concept in (await session.execute(level_query)).all():
        _, levels = by_concept.setdefault(concept.id, (concept, {}))
        state = level_state(row)
        if state is not None:
            levels[level_from_engine(row.mastery_level)] = state
    concept_key = LessonQuestionAttempt.question_snapshot["conceptId"].as_string()
    densest = {
        key: float(value)
        for key, value in (
            await session.execute(
                select(
                    concept_key,
                    func.max(
                        func.coalesce(
                            LessonQuestionAttempt.question_snapshot["textDensity"].as_float(),
                            UNSTATED_DENSITY,
                        )
                    ),
                )
                .where(LessonQuestionAttempt.student_id == learner_id, concept_key.is_not(None))
                .group_by(concept_key)
            )
        ).all()
    }
    reading = {
        row.concept_id: reading_state(row, max_text_density=densest.get(str(row.concept_id)))
        for row in await session.scalars(reading_query)
    }

    result = [
        ConceptRead(
            concept_id=concept.id,
            concept_name=readable_concept_name(concept.name),
            levels=levels,
            reading=reading.get(concept.id),
        )
        for concept, levels in by_concept.values()
        if levels or reading.get(concept.id)
    ]
    return sorted(result, key=lambda item: item.concept_name.casefold())


@dataclass(frozen=True)
class CohortCounts:
    learner_count: int
    #: Learners whose highest level reached, in order, is each level.
    at_level: dict[Level, int]
    #: Learners with evidence on the concept and no level reached yet.
    not_yet: int


async def cohort_counts(
    session: AsyncSession, learner_ids: Iterable[UUID], concept_id: UUID
) -> CohortCounts:
    """For a group on one concept: how many stand at each level.

    Counted over learners with any evidence on the concept, each once, at the
    highest level they have reached in order. The caller applies the floor.
    """

    ids = list(learner_ids)
    rows = (
        await session.scalars(
            select(StudentConceptLevelMastery).where(
                StudentConceptLevelMastery.concept_id == concept_id,
                StudentConceptLevelMastery.student_id.in_(ids),
            )
        )
        if ids
        else []
    )
    per_learner: dict[UUID, dict[Level, LevelState]] = {}
    for row in rows:
        state = level_state(row)
        if state is not None:
            per_learner.setdefault(row.student_id, {})[level_from_engine(row.mastery_level)] = state
    highest = Counter(highest_reached(levels) for levels in per_learner.values())
    return CohortCounts(
        learner_count=len(per_learner),
        at_level={level: highest.get(level, 0) for level in LEVELS},
        not_yet=highest.get(None, 0),
    )
