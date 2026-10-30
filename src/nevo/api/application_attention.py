"""Server-held learner away state; the browser reports visibility, not cognition."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from nevo.api.auth import PrincipalDependency
from nevo.api.consent import StudentLearningConsent
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_common import actor_user
from nevo.api.response_models import CamelResponse
from nevo.db.models.content import LessonSegment
from nevo.db.models.account import StudentClassEnrollment
from nevo.db.models.signal_event import LessonSession
from nevo.db.models.teacher_assignment import TeacherClassAssignment
from nevo.intelligence.away_time import transition

router = APIRouter(prefix="/api/v1", tags=["learning product"])


class AttentionTransition(BaseModel):
    action: Literal["away", "return"]
    segment_id: UUID = Field(alias="segmentId")


class AttentionState(CamelResponse):
    session_id: UUID
    student_id: UUID
    away: bool
    state: Literal["away", "returned", "unknown"]
    segment_id: UUID | None = None
    away_since: datetime | None = None
    recorded_at: datetime | None = None
    source: Literal["browser_visibility_report"] = "browser_visibility_report"


def _view(sitting: LessonSession) -> AttentionState:
    attention = (sitting.delivery_state or {}).get("attention") or {}
    current = attention.get("open") or {}
    latest = (attention.get("intervals") or [{}])[-1]
    recorded = current.get("awayAt") or latest.get("returnedAt")
    fresh = bool(recorded and datetime.fromisoformat(recorded) >= datetime.now(UTC) - timedelta(minutes=5))
    return AttentionState(
        session_id=sitting.id,
        student_id=sitting.student_id,
        away=bool(current) and fresh,
        state="away" if current and fresh else "returned" if recorded and fresh else "unknown",
        segment_id=current.get("segmentId"),
        away_since=current.get("awayAt"),
        recorded_at=recorded,
    )


@router.post("/students/me/sessions/{session_id}/attention", response_model=AttentionState)
async def record_attention_transition(
    session_id: UUID,
    payload: AttentionTransition,
    principal: PrincipalDependency,
    session: DatabaseSession,
    consent: StudentLearningConsent = None,
) -> AttentionState:
    del consent
    student = await actor_user(session, principal)
    if student.role.value != "student":
        raise HTTPException(403, detail={"code": "student_required"})
    sitting = await session.get(LessonSession, session_id, with_for_update=True)
    if sitting is None or sitting.student_id != student.id or sitting.ended_at is not None or sitting.lesson_id is None:
        raise HTTPException(404, detail={"code": "active_session_not_found"})
    segment = await session.get(LessonSegment, payload.segment_id)
    if segment is None or segment.lesson_id != sitting.lesson_id:
        raise HTTPException(404, detail={"code": "lesson_section_not_found"})
    transition(sitting, action=payload.action, segment_id=str(segment.id))
    await session.commit()
    return _view(sitting)


@router.get("/teachers/students/{student_id}/attention", response_model=AttentionState | None)
async def teacher_student_attention(
    student_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> AttentionState | None:
    if principal.role != "teacher":
        raise HTTPException(403, detail={"code": "class_teacher_required"})
    assignment = await session.scalar(
        select(TeacherClassAssignment.id)
        .join(StudentClassEnrollment, StudentClassEnrollment.class_id == TeacherClassAssignment.class_id)
        .where(
            TeacherClassAssignment.teacher_id == principal.user_id,
            TeacherClassAssignment.removed_at.is_(None),
            StudentClassEnrollment.student_id == student_id,
        ).limit(1)
    )
    if assignment is None:
        raise HTTPException(404, detail={"code": "student_not_in_teachers_class"})
    sitting = await session.scalar(
        select(LessonSession)
        .where(
            LessonSession.student_id == student_id,
            LessonSession.session_type == "lesson",
            LessonSession.ended_at.is_(None),
            LessonSession.started_at >= datetime.now(UTC) - timedelta(hours=10),
        )
        .order_by(LessonSession.started_at.desc()).limit(1)
    )
    return _view(sitting) if sitting is not None else None
