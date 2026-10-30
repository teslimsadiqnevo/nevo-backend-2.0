"""A learner may report outside work without creating fabricated mastery evidence."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from nevo.api.auth import PrincipalDependency
from nevo.api.casing import CAMEL_CONFIG
from nevo.api.consent import StudentLearningConsent
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_common import actor_user
from nevo.api.response_models import CamelResponse
from nevo.db.models.frontend_support import Concept
from nevo.db.models.out_of_school import OutOfSchoolLearning

router = APIRouter(prefix="/api/v1", tags=["learning product"])
ActivityKind = Literal["reading", "practice", "discussion", "paper_work"]


class OutsideWorkWrite(BaseModel):
    model_config = CAMEL_CONFIG
    concept_id: UUID
    activity_kind: ActivityKind
    client_event_id: UUID | None = None


class OutsideWorkResponse(CamelResponse):
    id: UUID
    concept_id: UUID
    activity_kind: ActivityKind
    recorded_at: datetime
    source: Literal["learner_report"] = "learner_report"


@router.post("/students/me/out-of-school-learning", response_model=OutsideWorkResponse, status_code=201)
async def report_outside_work(
    payload: OutsideWorkWrite,
    principal: PrincipalDependency,
    session: DatabaseSession,
    consent: StudentLearningConsent = None,
) -> OutsideWorkResponse:
    del consent
    student = await actor_user(session, principal)
    if student.role.value != "student":
        raise HTTPException(403, detail={"code": "student_required"})
    concept = await session.get(Concept, payload.concept_id)
    if concept is None or concept.school_id != student.school_id:
        raise HTTPException(404, detail={"code": "concept_not_found"})
    if payload.client_event_id:
        existing = await session.scalar(select(OutOfSchoolLearning).where(
            OutOfSchoolLearning.client_event_id == payload.client_event_id,
        ))
        if existing is not None:
            if existing.student_id != student.id or existing.concept_id != concept.id or existing.activity_kind != payload.activity_kind:
                raise HTTPException(409, detail={"code": "outside_work_event_conflict"})
            return OutsideWorkResponse(
                id=existing.id, concept_id=existing.concept_id,
                activity_kind=existing.activity_kind, recorded_at=existing.created_at,
            )
    row = OutOfSchoolLearning(
        student_id=student.id,
        concept_id=concept.id,
        activity_kind=payload.activity_kind,
        client_event_id=payload.client_event_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return OutsideWorkResponse(
        id=row.id, concept_id=concept.id, activity_kind=payload.activity_kind,
        recorded_at=row.created_at,
    )
