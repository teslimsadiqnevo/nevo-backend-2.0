from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import Field
from sqlalchemy import select

from nevo.api.auth import PrincipalDependency
from nevo.api.consent import StudentLearningConsent
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_common import actor_user, require_school_actor
from nevo.api.response_models import CamelResponse
from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.models.frontend_support import Concept
from nevo.intelligence.learning_runtime import (
    ONBOARDING_MODULES,
    onboarding_modules,
    refresh_onboarding,
)

router = APIRouter(prefix="/api/v1", tags=["intelligence"])


class OnboardingModule(CamelResponse):
    id: str
    completed: bool
    status: Literal["pending", "completed", "unavailable"] = "pending"


class OnboardingSubject(CamelResponse):
    subject_id: UUID
    name: str
    probe_available: bool
    placement_status: Literal["established", "unestablished"] = "unestablished"


class LearningReadiness(CamelResponse):
    complete: bool
    modules: list[OnboardingModule]
    subjects: list[OnboardingSubject]
    next_module: str | None
    probe_subject_id: UUID | None = None
    probe_policy: Literal["one_available_subject"] = "one_available_subject"


@router.get("/students/me/onboarding", response_model=LearningReadiness)
async def readiness(
    principal: PrincipalDependency, session: DatabaseSession, consent: StudentLearningConsent = None
):
    student = await actor_user(session, principal)
    if student.role != "student":
        raise HTTPException(403, detail="Student account required")
    subjects, available = await refresh_onboarding(session, student)
    completed = onboarding_modules(student.baseline_profile or {})
    unavailable = (student.baseline_profile or {}).get(
        "domain_probe_status"
    ) == "unavailable_at_onboarding"
    await session.commit()
    return LearningReadiness(
        complete=set(ONBOARDING_MODULES).issubset(completed),
        modules=[
            OnboardingModule(
                id=name,
                completed=name in completed,
                status="unavailable"
                if name == "domain_probe" and unavailable
                else "completed"
                if name in completed
                else "pending",
            )
            for name in ONBOARDING_MODULES
        ],
        subjects=[
            OnboardingSubject(
                subject_id=subject.id,
                name=subject.name,
                probe_available=subject.id in available,
                placement_status="established"
                if (
                    (student.baseline_profile or {})
                    .get("subject_placement_statuses", {})
                    .get(str(subject.id), {})
                    .get("status")
                    == "established"
                    or str(subject.id)
                    in ((student.baseline_profile or {}).get("subject_placements") or {})
                    or subject.name.casefold()
                    in ((student.baseline_profile or {}).get("subject_placements") or {})
                )
                else "unestablished",
            )
            for subject in subjects
        ],
        next_module=next((name for name in ONBOARDING_MODULES if name not in completed), None),
        probe_subject_id=next(
            (subject.id for subject in subjects if subject.id in available), None
        ),
    )


class CurriculumWrite(CamelResponse):
    curriculum_position: Annotated[float, Field(ge=0, le=1)]
    prerequisite_ids: list[UUID] = Field(default_factory=list, max_length=100)


class CurriculumResponse(CurriculumWrite):
    concept_id: UUID


class CurriculumFinding(CamelResponse):
    lesson_id: UUID
    segment_id: UUID
    code: Literal["assessed_concept_missing", "concept_not_in_school", "check_coverage_gap"]
    message: str


class CurriculumReadiness(CamelResponse):
    concept_count: int
    concepts_with_prerequisites: int
    prerequisite_review_required: bool
    findings: list[CurriculumFinding]


@router.get("/curriculum/readiness", response_model=CurriculumReadiness)
async def curriculum_readiness(principal: PrincipalDependency, session: DatabaseSession):
    actor = await require_school_actor(
        session, principal, roles={"teacher", "senco_admin", "other_admin"}
    )
    concepts = list(
        await session.scalars(select(Concept).where(Concept.school_id == actor.school_id))
    )
    valid = {str(row.id) for row in concepts}
    segments = list(
        await session.scalars(
            select(LessonSegment)
            .join(Lesson, Lesson.id == LessonSegment.lesson_id)
            .where(Lesson.school_id == actor.school_id)
            .order_by(LessonSegment.lesson_id, LessonSegment.sequence_order)
        )
    )
    findings = []
    gaps = {}
    for segment in segments:
        checkpoints = segment.comprehension_checkpoints or []
        calculation = segment.calculation_variant or {}
        assessed = [*checkpoints, *([calculation] if calculation else [])]
        for question in assessed:
            key = str(question.get("conceptId") or segment.concept_id or "")
            if key not in valid:
                findings.append(
                    CurriculumFinding(
                        lesson_id=segment.lesson_id,
                        segment_id=segment.id,
                        code="assessed_concept_missing" if not key else "concept_not_in_school",
                        message=(
                            "Link this assessed activity to a concept in this school's curriculum."
                        ),
                    )
                )
        gaps[segment.lesson_id] = 0 if assessed else gaps.get(segment.lesson_id, 0) + 1
        if gaps[segment.lesson_id] == 3:
            findings.append(
                CurriculumFinding(
                    lesson_id=segment.lesson_id,
                    segment_id=segment.id,
                    code="check_coverage_gap",
                    message=(
                        "This lesson has three consecutive sections without "
                        "an authored comprehension check."
                    ),
                )
            )
    linked = sum(bool(row.prerequisite_ids) for row in concepts)
    return CurriculumReadiness(
        concept_count=len(concepts),
        concepts_with_prerequisites=linked,
        prerequisite_review_required=bool(concepts) and linked == 0,
        findings=findings,
    )


class SegmentConceptWrite(CamelResponse):
    concept_id: UUID


@router.put("/segments/{segment_id}/concept", response_model=SegmentConceptWrite)
async def map_segment_concept(
    segment_id: UUID,
    payload: SegmentConceptWrite,
    principal: PrincipalDependency,
    session: DatabaseSession,
):
    actor = await require_school_actor(
        session, principal, roles={"teacher", "senco_admin", "other_admin"}
    )
    segment = await session.get(LessonSegment, segment_id, with_for_update=True)
    lesson = await session.get(Lesson, segment.lesson_id) if segment else None
    concept = await session.get(Concept, payload.concept_id)
    if (
        not lesson
        or lesson.school_id != actor.school_id
        or not concept
        or concept.school_id != actor.school_id
    ):
        raise HTTPException(404, detail="Segment or concept not found")
    segment.concept_id = concept.id
    segment.comprehension_checkpoints = [
        {**question, "conceptId": question.get("conceptId") or str(concept.id)}
        for question in segment.comprehension_checkpoints or []
    ]
    if segment.calculation_variant:
        segment.calculation_variant = {
            **segment.calculation_variant,
            "conceptId": segment.calculation_variant.get("conceptId") or str(concept.id),
        }
    await session.commit()
    return payload


class NextWorkResponse(CamelResponse):
    lesson_id: UUID
    concept_id: UUID
    concept_name: str
    segment_id: UUID | None
    segment_position: int = Field(ge=0, description="Zero-based position in lesson delivery order.")
    kind: Literal["review", "new_work"]


@router.get("/students/me/next-work", response_model=NextWorkResponse | None)
async def read_next_work(
    principal: PrincipalDependency,
    session: DatabaseSession,
    subject: str | None = None,
    consent: StudentLearningConsent = None,
):
    from nevo.intelligence.learning_runtime import ensure_onboarding
    from nevo.intelligence.progression import next_work

    student = await actor_user(session, principal)
    if student.role != "student":
        raise HTTPException(403, detail="Student account required")
    await ensure_onboarding(session, student)
    await session.commit()
    return await next_work(session, student, subject)


@router.put("/concepts/{concept_id}/curriculum", response_model=CurriculumResponse)
async def set_curriculum(
    concept_id: UUID,
    payload: CurriculumWrite,
    principal: PrincipalDependency,
    session: DatabaseSession,
):
    actor = await require_school_actor(
        session, principal, roles={"teacher", "senco_admin", "other_admin"}
    )
    concepts = {
        row.id: row
        for row in await session.scalars(
            select(Concept).where(Concept.school_id == actor.school_id).with_for_update()
        )
    }
    concept = concepts.get(concept_id)
    if concept is None or any(value not in concepts for value in payload.prerequisite_ids):
        raise HTTPException(404, detail="Concept not found")
    graph = {
        key: [UUID(value) for value in row.prerequisite_ids or []] for key, row in concepts.items()
    }
    graph[concept_id] = payload.prerequisite_ids

    checked = set()

    def visit(key, path):
        if key in path:
            raise HTTPException(
                422,
                detail={"code": "curriculum_cycle", "message": "An idea cannot depend on itself."},
            )
        if key in checked:
            return
        for parent in graph.get(key, []):
            visit(parent, path | {key})
        checked.add(key)

    visit(concept_id, set())
    concept.curriculum_position = payload.curriculum_position
    concept.prerequisite_ids = list(dict.fromkeys(str(value) for value in payload.prerequisite_ids))
    await session.commit()
    return CurriculumResponse(concept_id=concept.id, **payload.model_dump())


@router.get("/concepts/{concept_id}/curriculum", response_model=CurriculumResponse)
async def read_curriculum(
    concept_id: UUID, principal: PrincipalDependency, session: DatabaseSession
):
    actor = await require_school_actor(
        session, principal, roles={"teacher", "senco_admin", "other_admin"}
    )
    concept = await session.get(Concept, concept_id)
    if concept is None or concept.school_id != actor.school_id:
        raise HTTPException(404, detail="Concept not found")
    return CurriculumResponse(
        concept_id=concept.id,
        curriculum_position=concept.curriculum_position,
        prerequisite_ids=concept.prerequisite_ids,
    )
