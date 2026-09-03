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
    LessonClassProgressResponse,
    MisconceptionResponse,
    StudentProgressResponse,
    TeacherHomeResponse,
    TransformationMetricsResponse,
)
from nevo.db.models.account import Class, StudentClassEnrollment, User
from nevo.db.models.ask_nevo import AskNevoInteraction
from nevo.db.models.attention_flag import AttentionFlag
from nevo.db.models.content import ContentParseRun, Lesson, LessonSegment
from nevo.db.models.frontend_support import Concept, LessonAssignment
from nevo.db.models.mastery import StudentConceptMastery
from nevo.db.models.product import LessonProgress
from nevo.db.models.signal_event import LessonSession, SignalEvent
from nevo.db.models.teacher_assignment import TeacherClassAssignment
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


@router.get("/v1/teachers/me/home", response_model=TeacherHomeResponse)
async def teacher_home(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    actor = await require_school_actor(
        session,
        principal,
        roles={UserRole.TEACHER, UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN},
    )
    class_query = select(Class).where(
        Class.school_id == actor.school_id,
        Class.archived_at.is_(None),
    )
    if actor.role is UserRole.TEACHER:
        class_query = class_query.join(TeacherClassAssignment).where(
            TeacherClassAssignment.teacher_id == actor.id,
            TeacherClassAssignment.removed_at.is_(None),
        )
    classes = (await session.scalars(class_query.order_by(Class.name))).all()
    class_ids = [item.id for item in classes]
    enrollment_rows = (
        await session.execute(
            select(StudentClassEnrollment.class_id, StudentClassEnrollment.student_id).where(
                StudentClassEnrollment.class_id.in_(class_ids)
            )
        )
    ).all()
    students_by_class: dict[UUID, set[UUID]] = {item.id: set() for item in classes}
    for class_id, student_id in enrollment_rows:
        students_by_class[class_id].add(student_id)
    student_ids = {student_id for _, student_id in enrollment_rows}
    since = datetime.now(UTC) - timedelta(days=30)
    lesson_sessions = (
        await session.scalars(
            select(LessonSession).where(
                LessonSession.student_id.in_(student_ids),
                LessonSession.started_at >= since,
            )
        )
    ).all()
    signal_events = (
        await session.scalars(
            select(SignalEvent)
            .where(
                SignalEvent.student_id.in_(student_ids),
                SignalEvent.timestamp >= since,
            )
            .order_by(SignalEvent.timestamp.desc())
            .limit(10_000)
        )
    ).all()
    pulse = [
        _class_pulse(
            school_class,
            students_by_class[school_class.id],
            lesson_sessions,
            signal_events,
        )
        for school_class in classes
    ]
    return {
        "classLearningPulse": pulse,
        "recentActivity": await _teacher_recent_activity(
            session,
            school_id=actor.school_id,
            class_ids=class_ids,
            student_ids=student_ids,
        ),
    }


@router.get(
    "/v1/lessons/{lesson_id}/class-progress",
    response_model=LessonClassProgressResponse,
)
async def lesson_class_progress(
    lesson_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
    class_id: Annotated[UUID, Query(alias="classId")],
) -> dict[str, object]:
    actor = await require_school_actor(session, principal)
    await require_class_access(session, actor, class_id)
    lesson = await session.get(Lesson, lesson_id)
    if lesson is None or lesson.school_id != actor.school_id:
        raise HTTPException(status_code=404, detail="Lesson not found")
    student_ids = set(
        (
            await session.scalars(
                select(StudentClassEnrollment.student_id).where(
                    StudentClassEnrollment.class_id == class_id
                )
            )
        ).all()
    )
    assigned_ids = set(
        (
            await session.scalars(
                select(LessonAssignment.student_id).where(
                    LessonAssignment.lesson_id == lesson_id,
                    LessonAssignment.student_id.in_(student_ids),
                    LessonAssignment.status != "cancelled",
                )
            )
        ).all()
    )
    if assigned_ids:
        student_ids = assigned_ids
    segments = (
        await session.scalars(
            select(LessonSegment)
            .where(LessonSegment.lesson_id == lesson_id)
            .order_by(LessonSegment.sequence_order)
        )
    ).all()
    session_ids = set(
        (
            await session.scalars(
                select(LessonSession.id).where(
                    LessonSession.lesson_id == lesson_id,
                    LessonSession.student_id.in_(student_ids),
                )
            )
        ).all()
    )
    events = (
        await session.scalars(
            select(SignalEvent).where(SignalEvent.session_id.in_(session_ids))
        )
    ).all()
    rows = _segment_progress_rows(segments, events, len(student_ids))
    timed_rows = [item for item in rows if item["averageTimeSeconds"] is not None]
    slowest = max(timed_rows, key=lambda item: item["averageTimeSeconds"]) if timed_rows else None
    return {
        "lessonId": str(lesson_id),
        "classId": str(class_id),
        "assignedStudentCount": len(student_ids),
        "segments": rows,
        "slowestSegmentId": slowest["segmentId"] if slowest else None,
        "slowdownNote": slowest["note"] if slowest else None,
    }


@router.get("/engine-config/student/{student_id}", response_model=EngineConfigResponse)
async def engine_config(
    student_id: UUID, principal: PrincipalDependency, session: DatabaseSession
) -> dict[str, object]:
    if principal.role != UserRole.STUDENT or principal.user_id != student_id:
        raise HTTPException(status_code=404, detail="Student configuration not found")
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
    if len(interactions) < 3:
        return {
            "studentId": str(student_id),
            "periodDays": days,
            "interactionCount": 0,
            "categories": {},
            "helpfulResponseRate": None,
            "privacy": "withheld_below_minimum",
            "minimumInteractions": 3,
        }
    return {
        "studentId": str(student_id),
        "periodDays": days,
        "interactionCount": len(interactions),
        "categories": category_counts,
        "helpfulResponseRate": round(helpful / rated, 4) if rated else None,
        "privacy": "aggregate_only",
        "minimumInteractions": 3,
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
    mastery_average = sum(probabilities) / len(probabilities) if probabilities else None
    reflection, highlights = _progress_narrative(
        mastery_average=mastery_average,
        concept_count=len(mastery),
        practice_count=sum(item.practice_count for item, _ in mastery),
        lesson_count=len(lesson_rows),
        subject=subject,
    )
    return {
        "studentId": str(student_id),
        "subject": subject,
        "masteryAverage": round(mastery_average, 4) if mastery_average is not None else None,
        "concepts": [
            {
                "conceptId": str(item.concept_id),
                "lessonId": concept.lesson_id if concept else None,
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
                "positionBase": 0,
                "moduleNumber": progress.module_position + 1,
                "segmentNumber": progress.segment_position + 1,
                "updatedAt": progress.updated_at,
            }
            for progress, lesson in lesson_rows
        ],
        "reflection": reflection,
        "highlights": highlights,
    }


def _progress_narrative(
    *, mastery_average: float | None,
    concept_count: int,
    practice_count: int,
    lesson_count: int,
    subject: str | None,
) -> tuple[str, list[str]]:
    area = subject or "your recent learning"
    if mastery_average is None:
        return (
            f"Your {area} reflection will grow as you complete lessons.",
            ["Complete a lesson to start building your progress story."],
        )
    if mastery_average >= 0.8:
        reflection = f"You are applying most of the ideas you have practised in {area}."
    elif mastery_average >= 0.6:
        reflection = f"Your understanding in {area} is becoming steadier with practice."
    else:
        reflection = f"You are building familiarity with the ideas in {area}, one step at a time."
    highlights = [f"Worked with {concept_count} concept{'s' if concept_count != 1 else ''}."]
    if practice_count:
        practice_suffix = "s" if practice_count != 1 else ""
        highlights.append(
            f"Completed {practice_count} recorded practice attempt{practice_suffix}."
        )
    if lesson_count:
        lesson_suffix = "s" if lesson_count != 1 else ""
        highlights.append(f"Made progress in {lesson_count} lesson{lesson_suffix}.")
    return reflection, highlights


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


def _class_pulse(
    school_class: Class,
    student_ids: set[UUID],
    lesson_sessions: list[LessonSession],
    events: list[SignalEvent],
) -> dict[str, object]:
    class_sessions = [item for item in lesson_sessions if item.student_id in student_ids]
    class_events = [item for item in events if item.student_id in student_ids]
    engagement_values = [
        score
        for item in class_events
        if (score := _event_score(item.event_data, "engagementScore", "engagement")) is not None
    ]
    comprehension_values = [
        score
        for item in class_events
        if item.event_type is SignalEventType.COMPREHENSION_RESPONSE
        and (
            score := _event_score(
                item.event_data,
                "comprehensionScore",
                "score",
                "accuracy",
            )
        )
        is not None
    ]
    completed = sum(
        item.completion_status.value == "completed" for item in class_sessions
    )
    fallback_engagement = (
        round(completed / len(class_sessions) * 100, 1) if class_sessions else None
    )
    exit_attempts = sum(
        item.event_type is SignalEventType.EXIT_ATTEMPT for item in class_events
    )
    replay_count = sum(item.event_type is SignalEventType.REPLAY for item in class_events)
    focus = None
    if class_sessions:
        focus = round(
            max(
                0.0,
                100.0
                - min(45.0, exit_attempts / len(class_sessions) * 15)
                - min(25.0, replay_count / len(class_sessions) * 3),
            ),
            1,
        )
    return {
        "classId": str(school_class.id),
        "className": school_class.name,
        "studentCount": len(student_ids),
        "engagement": (
            round(sum(engagement_values) / len(engagement_values), 1)
            if engagement_values
            else fallback_engagement
        ),
        "comprehension": (
            round(sum(comprehension_values) / len(comprehension_values), 1)
            if comprehension_values
            else None
        ),
        "focus": focus,
    }


async def _teacher_recent_activity(
    session: DatabaseSession,
    *,
    school_id: UUID,
    class_ids: list[UUID],
    student_ids: set[UUID],
) -> list[dict[str, object]]:
    session_rows = (
        await session.execute(
            select(LessonSession, User, Lesson)
            .join(User, User.id == LessonSession.student_id)
            .outerjoin(Lesson, Lesson.id == LessonSession.lesson_id)
            .where(
                LessonSession.student_id.in_(student_ids),
                LessonSession.ended_at.is_not(None),
            )
            .order_by(LessonSession.ended_at.desc())
            .limit(12)
        )
    ).all()
    flag_rows = (
        await session.execute(
            select(AttentionFlag, User)
            .join(User, User.id == AttentionFlag.student_id)
            .where(User.school_id == school_id, AttentionFlag.student_id.in_(student_ids))
            .order_by(AttentionFlag.generated_at.desc())
            .limit(12)
        )
    ).all()
    assignment_rows = (
        await session.execute(
            select(LessonAssignment, Lesson)
            .join(Lesson, Lesson.id == LessonAssignment.lesson_id)
            .where(
                LessonAssignment.class_id.in_(class_ids),
                LessonAssignment.status != "cancelled",
            )
            .order_by(LessonAssignment.assigned_at.desc())
            .limit(12)
        )
    ).all()
    activity: list[dict[str, object]] = []
    for lesson_session, student, lesson in session_rows:
        student_name = student.first_name or "A student"
        activity.append(
            {
                "id": f"session:{lesson_session.id}",
                "activityType": "lesson_completed",
                "occurredAt": lesson_session.ended_at,
                "title": f"{student_name} completed a lesson",
                "detail": lesson.title if lesson else "Lesson activity",
                "studentId": str(student.id),
                "lessonId": str(lesson.id) if lesson else None,
                "actionTarget": f"/teacher/students/{student.id}",
            }
        )
    for flag, student in flag_rows:
        student_name = student.first_name or "A student"
        activity.append(
            {
                "id": f"flag:{flag.id}",
                "activityType": "attention_flag",
                "occurredAt": flag.generated_at,
                "title": f"Review {student_name}'s recent pattern",
                "detail": flag.description,
                "studentId": str(student.id),
                "actionTarget": f"/teacher/students/{student.id}",
            }
        )
    seen_assignments: set[tuple[UUID | None, UUID]] = set()
    for assignment, lesson in assignment_rows:
        key = (assignment.class_id, lesson.id)
        if key in seen_assignments:
            continue
        seen_assignments.add(key)
        activity.append(
            {
                "id": f"assignment:{assignment.id}",
                "activityType": "lesson_assigned",
                "occurredAt": assignment.assigned_at,
                "title": "Lesson assigned",
                "detail": lesson.title,
                "classId": str(assignment.class_id) if assignment.class_id else None,
                "lessonId": str(lesson.id),
                "actionTarget": f"/teacher/lessons/{lesson.id}",
            }
        )
    return sorted(activity, key=lambda item: item["occurredAt"], reverse=True)[:20]


def _segment_progress_rows(
    segments: list[LessonSegment],
    events: list[SignalEvent],
    assigned_student_count: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    completion_types = {
        SignalEventType.TIME_ON_SEGMENT,
        SignalEventType.COMPREHENSION_RESPONSE,
        SignalEventType.MODALITY_SWITCH_OUTCOME,
    }
    for segment in segments:
        matching = [
            event
            for event in events
            if str(event.event_data.get("segmentId") or event.event_data.get("segment_id") or "")
            in {str(segment.id), segment.segment_key}
        ]
        completed_students = {
            event.student_id for event in matching if event.event_type in completion_types
        }
        times = [
            seconds
            for event in matching
            if (
                seconds := _time_seconds(
                    event.event_data.get("timeOnSegment")
                    or event.event_data.get("durationSeconds")
                    or event.event_data.get("durationMs")
                )
            )
            is not None
        ]
        average = round(sum(times) / len(times), 1) if times else None
        slowdown_count = (
            sum(value > max(90.0, average * 1.25) for value in times)
            if average is not None
            else 0
        )
        completion_rate = (
            round(len(completed_students) / assigned_student_count, 4)
            if assigned_student_count
            else 0.0
        )
        note = None
        if slowdown_count:
            note = f"{slowdown_count} students spent longer here than the class pattern."
        elif assigned_student_count and completion_rate < 0.5:
            note = "Fewer than half of assigned students have completed this segment."
        rows.append(
            {
                "segmentId": str(segment.id),
                "segmentKey": segment.segment_key,
                "title": segment.title,
                "sequenceOrder": segment.sequence_order,
                "assignedStudentCount": assigned_student_count,
                "completionCount": len(completed_students),
                "completionRate": completion_rate,
                "averageTimeSeconds": average,
                "slowdownCount": slowdown_count,
                "note": note,
            }
        )
    return rows


def _event_score(data: dict[str, object], *keys: str) -> float | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, int | float):
            score = float(value)
            if score <= 1:
                score *= 100
            return max(0.0, min(100.0, score))
    return None


def _time_seconds(value: object) -> float | None:
    if not isinstance(value, int | float):
        return None
    seconds = float(value)
    if seconds > 1_000:
        seconds /= 1_000
    return max(0.0, seconds)
