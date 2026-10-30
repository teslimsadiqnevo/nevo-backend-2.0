"""No-camera paper-work evidence, marked from approved steps without model judgment."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from nevo.api.auth import PrincipalDependency
from nevo.api.casing import CAMEL_CONFIG
from nevo.api.consent import StudentLearningConsent
from nevo.api.dependencies import DatabaseSession
from nevo.api.lesson_review import approved_check_ids
from nevo.api.product_common import actor_user
from nevo.api.response_models import CamelResponse
from nevo.content_parsing.answers import answer_matches
from nevo.db.models.content import LessonSegment
from nevo.db.models.paper_work import PaperWorkEvidence
from nevo.db.models.signal_event import LessonSession

router = APIRouter(prefix="/api/v1", tags=["learning product"])


class TypedPaperStep(BaseModel):
    model_config = CAMEL_CONFIG
    step_id: str = Field(min_length=1, max_length=120)
    answer: str | int | float

    @field_validator("answer")
    @classmethod
    def bounded_answer(cls, answer):
        if isinstance(answer, bool) or len(str(answer)) > 500:
            raise ValueError("A paper step answer must be a short text or number")
        return answer


class TypedPaperWorkWrite(BaseModel):
    model_config = CAMEL_CONFIG
    session_id: UUID
    segment_id: UUID
    question_id: str = Field(min_length=1, max_length=160)
    client_submission_id: UUID | None = None
    steps: list[TypedPaperStep] = Field(min_length=1, max_length=8)


class PaperStepMark(CamelResponse):
    step_id: str
    matched: bool


class TypedPaperWorkResponse(CamelResponse):
    evidence_id: UUID
    status: Literal["matched", "needs_work"]
    marks: list[PaperStepMark]
    recorded_at: datetime
    counts_as_check_pass: Literal[False] = False
    source: Literal["typed_no_camera"] = "typed_no_camera"


def _response(row: PaperWorkEvidence) -> TypedPaperWorkResponse:
    return TypedPaperWorkResponse(
        evidence_id=row.id,
        status="matched" if all(mark["matched"] for mark in row.marks) else "needs_work",
        marks=[PaperStepMark.model_validate(mark) for mark in row.marks],
        recorded_at=row.created_at,
    )


@router.post("/students/me/lessons/{lesson_id}/paper-work/typed", response_model=TypedPaperWorkResponse, status_code=201)
async def submit_typed_paper_work(
    lesson_id: UUID,
    payload: TypedPaperWorkWrite,
    principal: PrincipalDependency,
    session: DatabaseSession,
    consent: StudentLearningConsent = None,
) -> TypedPaperWorkResponse:
    del consent
    student = await actor_user(session, principal)
    if student.role.value != "student":
        raise HTTPException(403, detail={"code": "student_required"})
    sitting = await session.get(LessonSession, payload.session_id)
    segment = await session.get(LessonSegment, payload.segment_id)
    if (
        sitting is None or sitting.student_id != student.id or sitting.lesson_id != lesson_id
        or sitting.ended_at is not None
        or segment is None or segment.lesson_id != lesson_id
    ):
        raise HTTPException(404, detail={"code": "lesson_work_not_found"})
    if payload.client_submission_id:
        existing = await session.scalar(select(PaperWorkEvidence).where(
            PaperWorkEvidence.client_submission_id == payload.client_submission_id,
        ))
        if existing is not None:
            if (
                existing.student_id != student.id or existing.session_id != sitting.id
                or existing.segment_id != segment.id or existing.question_id != payload.question_id
            ):
                raise HTTPException(409, detail={"code": "paper_work_submission_conflict"})
            return _response(existing)
    approved = await approved_check_ids(session, lesson_id)
    if (str(segment.id), payload.question_id) not in approved:
        raise HTTPException(409, detail={"code": "paper_work_steps_not_approved"})
    question = next((item for item in segment.comprehension_checkpoints or []
                     if str(item.get("id")) == payload.question_id), None)
    expected = question.get("guidedSteps") if question else None
    if not expected or question.get("guidedStepsReviewStatus") != "approved":
        raise HTTPException(409, detail={"code": "paper_work_steps_not_approved"})
    if any(step.get("answerKey") is None for step in expected):
        raise HTTPException(409, detail={"code": "paper_work_steps_unmarkable"})
    expected_ids = [str(step.get("id")) for step in expected]
    submitted_ids = [step.step_id for step in payload.steps]
    if submitted_ids != expected_ids:
        raise HTTPException(422, detail={"code": "paper_work_steps_out_of_order"})
    marks = [
        {"stepId": step.step_id, "matched": answer_matches(step.answer, expected[index]) is True}
        for index, step in enumerate(payload.steps)
    ]
    row = PaperWorkEvidence(
        student_id=student.id,
        session_id=sitting.id,
        lesson_id=lesson_id,
        segment_id=segment.id,
        question_id=payload.question_id,
        client_submission_id=payload.client_submission_id,
        marks=marks,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _response(row)
