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
from nevo.db.models.account import StudentClassEnrollment
from nevo.db.models.frontend_support import Concept
from nevo.db.models.probe import ProbeItem
from nevo.db.models.subject import ClassSubject, SchoolSubject
from nevo.intelligence.learning_runtime import ONBOARDING_MODULES, onboarding_modules

router = APIRouter(prefix="/api/v1", tags=["intelligence"])


class OnboardingModule(CamelResponse):
    id: str
    completed: bool


class OnboardingSubject(CamelResponse):
    subject_id: UUID
    name: str
    probe_available: bool


class LearningReadiness(CamelResponse):
    complete: bool
    modules: list[OnboardingModule]
    subjects: list[OnboardingSubject]
    next_module: str | None


@router.get("/students/me/onboarding", response_model=LearningReadiness)
async def readiness(
    principal: PrincipalDependency, session: DatabaseSession, consent: StudentLearningConsent = None
):
    student = await actor_user(session, principal)
    if student.role != "student":
        raise HTTPException(403, detail="Student account required")
    completed = onboarding_modules(student.baseline_profile or {})
    subjects = list(
        await session.scalars(
            select(SchoolSubject)
            .join(
                ClassSubject,
                ClassSubject.school_subject_id == SchoolSubject.id,
            )
            .join(StudentClassEnrollment, StudentClassEnrollment.class_id == ClassSubject.class_id)
            .where(
                StudentClassEnrollment.student_id == student.id,
                SchoolSubject.school_id == student.school_id,
            )
            .distinct()
            .order_by(SchoolSubject.name)
        )
    )
    available = set(
        await session.scalars(
            select(ProbeItem.school_subject_id)
            .where(
                ProbeItem.school_id == student.school_id,
                ProbeItem.retired.is_(False),
            )
            .distinct()
        )
    )
    return LearningReadiness(
        complete=set(ONBOARDING_MODULES).issubset(completed),
        modules=[
            OnboardingModule(id=name, completed=name in completed) for name in ONBOARDING_MODULES
        ],
        subjects=[
            OnboardingSubject(
                subject_id=subject.id, name=subject.name, probe_available=subject.id in available
            )
            for subject in subjects
        ],
        next_module=next((name for name in ONBOARDING_MODULES if name not in completed), None),
    )


class CurriculumWrite(CamelResponse):
    curriculum_position: Annotated[float, Field(ge=0, le=1)]
    prerequisite_ids: list[UUID] = Field(default_factory=list, max_length=100)


class CurriculumResponse(CurriculumWrite):
    concept_id: UUID


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
    from nevo.intelligence.learning_runtime import require_onboarding
    from nevo.intelligence.progression import next_work

    student = await actor_user(session, principal)
    if student.role != "student":
        raise HTTPException(403, detail="Student account required")
    require_onboarding(student)
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
