from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from nevo.api.auth import PrincipalDependency
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_common import (
    require_class_access,
    require_school_actor,
    require_student_access,
)
from nevo.api.response_models import (
    AdaptationResponse,
    ConversationEvidenceResponse,
    EngineConfigResponse,
    MisconceptionResponse,
    StudentProgressResponse,
    TransformationMetricsResponse,
)
from nevo.db.models.account import StudentClassEnrollment, User
from nevo.db.models.ask_nevo import AskNevoInteraction
from nevo.db.models.content import ContentParseRun, Lesson
from nevo.db.models.frontend_support import Concept
from nevo.db.models.mastery import StudentConceptMastery
from nevo.db.models.product import LessonProgress
from nevo.db.models.signal_event import LessonSession, SignalEvent
from nevo.domain.accounts.vocabulary import UserRole
from nevo.domain.signal_events.vocabulary import SignalEventType

router = APIRouter(prefix="/api", tags=["intelligence"])

ADAPTATION_EVENTS = {
    SignalEventType.SIMPLIFY_TRIGGER,
    SignalEventType.EXPAND_TRIGGER,
    SignalEventType.SLOWER_TRIGGER,
    SignalEventType.MODALITY_SUGGESTION_ACCEPTED,
    SignalEventType.MODALITY_MANUAL_SWITCH,
    SignalEventType.MODALITY_SWITCH_OUTCOME,
    SignalEventType.ADAPTATION_SUPPRESSED,
}


@router.get("/engine-config/student/{student_id}", response_model=EngineConfigResponse)
async def engine_config(
    student_id: UUID, principal: PrincipalDependency, session: DatabaseSession
) -> dict[str, object]:
    await require_student_access(session, principal, student_id)
    student = await session.get(User, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    return {
        "studentId": str(student_id),
        "configured": bool(student.engine_config),
        "engineConfig": dict(student.engine_config),
        "baselineVersion": student.baseline_profile.get("version"),
    }


@router.get("/adaptations/student/{student_id}", response_model=list[AdaptationResponse])
async def student_adaptations(
    student_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, object]]:
    await require_student_access(session, principal, student_id)
    rows = (
        await session.execute(
            select(SignalEvent, LessonSession.lesson_id, Lesson.title)
            .join(LessonSession, LessonSession.id == SignalEvent.session_id)
            .outerjoin(Lesson, Lesson.id == LessonSession.lesson_id)
            .where(
                SignalEvent.student_id == student_id,
                SignalEvent.event_type.in_(ADAPTATION_EVENTS),
            )
            .order_by(SignalEvent.timestamp.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "id": str(event.id),
            "studentId": str(student_id),
            "lessonId": str(lesson_id),
            "lessonTitle": title or "Lesson",
            "timestamp": event.timestamp,
            "eventType": event.event_type.value,
            "trigger": _plain_trigger(event),
            "adaptation": _plain_adaptation(event),
            "suppressed": event.event_type is SignalEventType.ADAPTATION_SUPPRESSED,
        }
        for event, lesson_id, title in rows
    ]


@router.get(
    "/conversation-evidence/student/{student_id}",
    response_model=ConversationEvidenceResponse,
)
async def conversation_evidence(
    student_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> dict[str, object]:
    await require_student_access(session, principal, student_id)
    since = datetime.now(UTC) - timedelta(days=days)
    interactions = (
        await session.scalars(
            select(AskNevoInteraction)
            .where(
                AskNevoInteraction.created_at >= since,
                AskNevoInteraction.context_ids["studentId"].as_string() == str(student_id),
            )
            .order_by(AskNevoInteraction.created_at.desc())
        )
    ).all()
    category_counts: dict[str, int] = {}
    helpful = 0
    rated = 0
    for item in interactions:
        category_counts[item.question_category.value] = (
            category_counts.get(item.question_category.value, 0) + 1
        )
        if item.response_helpful is not None:
            rated += 1
            helpful += int(item.response_helpful)
    return {
        "studentId": str(student_id),
        "periodDays": days,
        "interactionCount": len(interactions),
        "categories": category_counts,
        "helpfulResponseRate": round(helpful / rated, 4) if rated else None,
        "recentEvidence": [
            {
                "category": item.question_category.value,
                "currentPage": item.current_page,
                "contextIds": item.context_ids,
                "helpful": item.response_helpful,
                "createdAt": item.created_at,
            }
            for item in interactions[:20]
        ],
        "privacy": "Question and response transcripts are not stored.",
    }


@router.get("/misconceptions/class/{class_id}", response_model=list[MisconceptionResponse])
async def class_misconceptions(
    class_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
    minimum_students: Annotated[int, Query(alias="minimumStudents", ge=3, le=50)] = 3,
) -> list[dict[str, object]]:
    await require_class_access(session, principal, class_id)
    rows = (
        await session.execute(
            select(
                StudentConceptMastery.concept_id,
                Concept.name,
                StudentConceptMastery.last_failure_attribution,
                func.count(func.distinct(StudentConceptMastery.student_id)),
            )
            .join(
                StudentClassEnrollment,
                StudentClassEnrollment.student_id == StudentConceptMastery.student_id,
            )
            .outerjoin(Concept, Concept.id == StudentConceptMastery.concept_id)
            .where(
                StudentClassEnrollment.class_id == class_id,
                StudentConceptMastery.last_response_correct.is_(False),
            )
            .group_by(
                StudentConceptMastery.concept_id,
                Concept.name,
                StudentConceptMastery.last_failure_attribution,
            )
            .having(func.count(func.distinct(StudentConceptMastery.student_id)) >= minimum_students)
            .order_by(func.count(func.distinct(StudentConceptMastery.student_id)).desc())
        )
    ).all()
    return [
        {
            "conceptId": str(concept_id),
            "conceptName": name or "Concept",
            "pattern": attribution.value,
            "studentCount": count,
            "description": _misconception_description(name, attribution.value, count),
        }
        for concept_id, name, attribution, count in rows
    ]


@router.get("/transformation-metrics", response_model=TransformationMetricsResponse)
async def transformation_metrics(
    principal: PrincipalDependency,
    session: DatabaseSession,
    scope: Literal["student", "cohort", "school"] = Query(default="school"),
    student_id: Annotated[UUID | None, Query(alias="studentId")] = None,
    cohort_id: Annotated[UUID | None, Query(alias="cohortId")] = None,
) -> dict[str, object]:
    actor = await require_school_actor(session, principal)
    student_ids = await _scope_students(scope, student_id, cohort_id, actor, principal, session)
    lesson_filter = select(Lesson.id).where(Lesson.school_id == actor.school_id)
    lessons = (
        await session.scalar(
            select(func.count(Lesson.id)).where(Lesson.school_id == actor.school_id)
        )
        or 0
    )
    parse_runs = (
        await session.scalar(
            select(func.count(ContentParseRun.id)).where(
                ContentParseRun.lesson_id.in_(lesson_filter)
            )
        )
        or 0
    )
    session_query = select(func.count(LessonSession.id)).where(
        LessonSession.lesson_id.in_(lesson_filter)
    )
    adaptation_query = select(func.count(SignalEvent.id)).where(
        SignalEvent.event_type.in_(ADAPTATION_EVENTS)
    )
    if student_ids is not None:
        session_query = session_query.where(LessonSession.student_id.in_(student_ids))
        adaptation_query = adaptation_query.where(SignalEvent.student_id.in_(student_ids))
    lesson_sessions = await session.scalar(session_query) or 0
    adaptations = await session.scalar(adaptation_query) or 0
    return {
        "scope": scope,
        "studentCount": len(student_ids)
        if student_ids is not None
        else await _student_count(session, actor.school_id),
        "lessonsTransformed": int(lessons),
        "transformationRuns": int(parse_runs),
        "lessonSessions": int(lesson_sessions),
        "adaptationsApplied": int(adaptations),
        "adaptationsPerSession": round(int(adaptations) / int(lesson_sessions), 3)
        if lesson_sessions
        else 0.0,
    }


@router.get("/students/{student_id}/progress", response_model=StudentProgressResponse)
async def student_progress(
    student_id: UUID, principal: PrincipalDependency, session: DatabaseSession
) -> dict[str, object]:
    await require_student_access(session, principal, student_id)
    return await _progress_payload(session, student_id, subject=None)


@router.get("/students/{student_id}/progress/{subject}", response_model=StudentProgressResponse)
async def student_subject_progress(
    student_id: UUID,
    subject: str,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    await require_student_access(session, principal, student_id)
    return await _progress_payload(session, student_id, subject=subject)


async def _scope_students(scope, student_id, cohort_id, actor, principal, session):
    if scope == "student":
        if student_id is None:
            raise HTTPException(status_code=422, detail="studentId is required for student scope")
        await require_student_access(session, principal, student_id)
        return [student_id]
    if scope == "cohort":
        if cohort_id is None:
            raise HTTPException(status_code=422, detail="cohortId is required for cohort scope")
        await require_class_access(session, actor, cohort_id)
        return list(
            (
                await session.scalars(
                    select(StudentClassEnrollment.student_id).where(
                        StudentClassEnrollment.class_id == cohort_id
                    )
                )
            ).all()
        )
    return None


async def _student_count(session, school_id):
    return int(
        await session.scalar(
            select(func.count(User.id)).where(
                User.school_id == school_id, User.role == UserRole.STUDENT
            )
        )
        or 0
    )


async def _progress_payload(session, student_id, subject):
    mastery_query = (
        select(StudentConceptMastery, Concept)
        .outerjoin(Concept, Concept.id == StudentConceptMastery.concept_id)
        .where(StudentConceptMastery.student_id == student_id)
    )
    if subject:
        mastery_query = mastery_query.where(func.lower(Concept.subject) == subject.casefold())
    mastery = (await session.execute(mastery_query)).all()
    lesson_rows = (
        await session.execute(
            select(LessonProgress, Lesson)
            .join(Lesson, Lesson.id == LessonProgress.lesson_id)
            .where(LessonProgress.student_id == student_id)
            .order_by(LessonProgress.updated_at.desc())
        )
    ).all()
    if subject:
        lesson_rows = [
            row
            for row in lesson_rows
            if str(row[1].source_reference.get("subject", "")).casefold() == subject.casefold()
        ]
    probabilities = [item.mastery_probability_concept for item, _ in mastery]
    return {
        "studentId": str(student_id),
        "subject": subject,
        "masteryAverage": round(sum(probabilities) / len(probabilities), 4)
        if probabilities
        else None,
        "concepts": [
            {
                "conceptId": str(item.concept_id),
                "name": concept.name if concept else "Concept",
                "subject": concept.subject if concept else None,
                "understanding": round(item.mastery_probability_concept, 4),
                "reading": round(item.mastery_probability_reading, 4),
                "practiceCount": item.practice_count,
            }
            for item, concept in mastery
        ],
        "lessons": [
            {
                "lessonId": str(lesson.id),
                "title": lesson.title,
                "status": progress.status,
                "modulePosition": progress.module_position,
                "segmentPosition": progress.segment_position,
                "updatedAt": progress.updated_at,
            }
            for progress, lesson in lesson_rows
        ],
    }


def _plain_trigger(event: SignalEvent) -> str:
    data = event.event_data
    signals = data.get("triggerSignals") or data.get("signals")
    if isinstance(signals, list) and signals:
        return " + ".join(str(item).replace("_", " ") for item in signals)
    return event.event_type.value.replace("_", " ").capitalize()


def _plain_adaptation(event: SignalEvent) -> str:
    data = event.event_data
    source = data.get("fromModality") or data.get("from")
    target = data.get("toModality") or data.get("to") or data.get("modality")
    if source and target:
        return f"{source} to {target}"
    return str(data.get("adaptation") or event.event_type.value.replace("_", " ")).capitalize()


def _misconception_description(name: str | None, attribution: str, count: int) -> str:
    concept = name or "this concept"
    reason = "reading load" if attribution == "reading" else "the concept itself"
    return (
        f"{count} students may need another example of {concept}; the pattern points to {reason}."
    )
