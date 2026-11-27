"""The mastery read for school staff: per learner, and per year group.

S21, section 7 of the engine specification. The data is nevo.mastery.read;
this is two of its three views. The third, a learner's own, is GET /me/mastery.

Teacher and admin, per learner: all three level states for each concept, as
drawn in the By Level design, with reading beside them and never as a level.

Reports, per year group on a concept: how many learners stand at each level,
under the same floor as every other year-group figure. Below it the counts
are withheld and say so, rather than reading as zeros.

No probability, score or percentage is returned by either.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from nevo.api.auth import PrincipalDependency
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_common import require_school_actor, require_student_access
from nevo.api.response_models import CamelResponse
from nevo.api.transformation_metrics import REPORTING_FLOOR, WITHHELD_LABEL
from nevo.content_parsing.concept_names import readable_concept_name
from nevo.db.models.account import Class, StudentClassEnrollment, User
from nevo.db.models.frontend_support import Concept
from nevo.mastery import read

router = APIRouter(prefix="/api/v1", tags=["mastery"])

STAFF_ROLES = {"teacher", "senco_admin", "other_admin"}

Level = Literal["knowing_and_understanding", "application", "analysis_and_evaluation"]
LevelState = Literal["reached", "working", "not"]
ReadingState = Literal["at", "support", "none"]


class ConceptMasteryRead(CamelResponse):
    concept_id: UUID
    concept_name: str
    #: One entry per level something was observed at. A level with no entry
    #: has nothing observed, which is not the same as `not`.
    levels: dict[Level, LevelState]
    #: Beside the levels, never one of them. Omitted when nothing is observed.
    reading: ReadingState | None = None


class LearnerMasteryRead(CamelResponse):
    student_id: UUID
    concepts: list[ConceptMasteryRead]


class CohortMasteryRead(CamelResponse):
    year_group: str
    concept_id: UUID
    concept_name: str
    #: Learners in the year group with any evidence on the concept.
    learner_count: int
    reporting_floor: int
    suppressed: bool
    #: Each learner once, at the highest level reached in order. Null when
    #: suppressed.
    at_level: dict[Level, int] | None = None
    #: Learners with evidence and no level reached yet. Null when suppressed.
    not_yet: int | None = None
    withheld_label: str | None = None


def concept_read(item: read.ConceptRead) -> ConceptMasteryRead:
    return ConceptMasteryRead(
        concept_id=item.concept_id,
        concept_name=item.concept_name,
        levels=dict(item.levels),
        reading=item.reading,
    )


@router.get(
    "/students/{student_id}/mastery",
    response_model=LearnerMasteryRead,
    response_model_exclude_none=True,
)
async def learner_mastery(
    student_id: UUID, principal: PrincipalDependency, session: DatabaseSession
) -> LearnerMasteryRead:
    """Every concept a learner has evidence on, a state per level."""

    if principal.role not in STAFF_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "staff_role_required"})
    actor = await require_student_access(session, principal, student_id)
    learner = await session.get(User, student_id)
    if learner is None or learner.school_id != actor.school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Student not found")
    items = await read.read_learner(
        session, student_id, concepts=Concept.school_id == actor.school_id
    )
    return LearnerMasteryRead(student_id=student_id, concepts=[concept_read(i) for i in items])


@router.get(
    "/reports/year-groups/{year_group}/concepts/{concept_id}/mastery",
    response_model=CohortMasteryRead,
    response_model_exclude_none=True,
)
async def year_group_concept_mastery(
    year_group: str,
    concept_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> CohortMasteryRead:
    """How many learners in a year group stand at each level on one concept.

    The year group is the label a school wrote on its classes, matched as
    the other year-group reports match it: trimmed, any case.
    """

    actor = await require_school_actor(session, principal)
    label = " ".join(year_group.split())
    concept = await session.get(Concept, concept_id)
    if not label or concept is None or concept.school_id != actor.school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    learners = list(
        await session.scalars(
            select(StudentClassEnrollment.student_id)
            .join(Class, Class.id == StudentClassEnrollment.class_id)
            .where(
                Class.school_id == actor.school_id,
                Class.archived_at.is_(None),
                func.lower(func.btrim(Class.year_group)) == label.casefold(),
            )
            .distinct()
        )
    )
    counts = await read.cohort_counts(session, learners, concept_id)
    base = {
        "year_group": label,
        "concept_id": concept_id,
        "concept_name": readable_concept_name(concept.name),
        "learner_count": counts.learner_count,
        "reporting_floor": REPORTING_FLOOR,
    }
    if counts.learner_count < REPORTING_FLOOR:
        return CohortMasteryRead(**base, suppressed=True, withheld_label=WITHHELD_LABEL)
    return CohortMasteryRead(
        **base,
        suppressed=False,
        at_level=dict(counts.at_level),
        not_yet=counts.not_yet,
    )
