from dataclasses import replace
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import or_, select

from nevo.api.product_common import actor_user
from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.models.frontend_support import LessonAssignment
from nevo.db.models.mastery import StudentConceptScaffoldState
from nevo.db.models.product import LessonQuestionAttempt
from nevo.db.models.signal_event import LessonSession, SignalEvent
from nevo.domain.intelligence.vocabulary import AdaptationMode, ContentModality
from nevo.domain.signal_events.vocabulary import LessonCompletionStatus, SignalEventType
from nevo.intelligence.adaptation import ADAPTATION_HISTORY_EVENT_TYPES
from nevo.intelligence.entities import AdaptationRequest, ContentSegment
from nevo.intelligence.learning_runtime import require_onboarding


def repeated_near_miss(attempts):
    if len(attempts) < 2:
        return False
    first, second = attempts[:2]
    if first.correct is not False or second.correct is not False:
        return False
    if first.question_snapshot.get("conceptId") != second.question_snapshot.get("conceptId"):
        return False
    try:
        return all(
            0
            < abs(float(item.answer) - float(item.question_snapshot["answerKey"]))
            <= max(1, abs(float(item.question_snapshot["answerKey"])) * 0.25)
            for item in (first, second)
        )
    except (ValueError, TypeError, KeyError):
        return False


async def prepare_adaptation(session, principal, payload, signals):
    """Use stored content and session history, not optional client guardrails."""
    actor = await actor_user(session, principal)
    if actor.role != "student":
        raise HTTPException(
            403,
            detail={"code": "student_context_forbidden", "message": "Student account required."},
        )
    require_onboarding(actor)
    lesson = await session.get(Lesson, payload.lesson_id)
    assignment = await session.scalar(
        select(LessonAssignment.id).where(
            LessonAssignment.student_id == actor.id,
            LessonAssignment.lesson_id == payload.lesson_id,
            LessonAssignment.status != "cancelled",
            or_(
                LessonAssignment.available_from.is_(None),
                LessonAssignment.available_from <= datetime.now(UTC),
            ),
        )
    )
    if lesson is None or lesson.school_id != actor.school_id or assignment is None:
        raise HTTPException(404, detail="Lesson not found")
    query = select(LessonSession).where(
        LessonSession.student_id == actor.id,
        LessonSession.lesson_id == lesson.id,
        LessonSession.completion_status == LessonCompletionStatus.IN_PROGRESS,
    )
    if payload.session_id:
        query = query.where(LessonSession.id == payload.session_id)
    sitting = await session.scalar(
        query.order_by(LessonSession.started_at.desc()).limit(1).with_for_update()
    )
    in_lesson = payload.mode is AdaptationMode.IN_LESSON or signals.current_segment_id is not None
    if in_lesson and sitting is None:
        raise HTTPException(
            409,
            detail={
                "code": "lesson_session_required",
                "message": "Open the lesson before continuing.",
            },
        )
    stored = list(
        await session.scalars(
            select(LessonSegment)
            .where(
                LessonSegment.lesson_id == lesson.id,
            )
            .order_by(LessonSegment.sequence_order)
        )
    )
    by_key = {key: row for row in stored for key in (str(row.id), row.segment_key)}
    states = {
        str(row.concept_id): row.current_intensity
        for row in await session.scalars(
            select(StudentConceptScaffoldState).where(
                StudentConceptScaffoldState.student_id == actor.id
            )
        )
    }
    segments = []
    for declared in payload.segments:
        row = by_key.get(declared.id)
        if row is None:
            raise HTTPException(404, detail="Lesson segment not found")
        calculation = row.calculation_variant or {}
        checkpoints = row.comprehension_checkpoints or []
        concept_id = (
            row.concept_id
            or calculation.get("conceptId")
            or next((item.get("conceptId") for item in checkpoints if item.get("conceptId")), None)
        )
        steps = calculation.get("steps") or []
        hints = tuple(str(item["hint"]) for item in [*steps, *checkpoints] if item.get("hint"))
        questions = tuple(str(item["prompt"]) for item in steps if item.get("prompt"))
        if not questions:
            questions = tuple(
                str(question)
                for item in checkpoints
                for question in item.get("guidedQuestions", [])
                if isinstance(question, str) and question.strip()
            )
        segments.append(
            ContentSegment(
                id=declared.id,
                segment_type=declared.segment_type,
                available_modalities=tuple(
                    ContentModality(value) for value in row.available_modalities
                ),
                concept_id=str(concept_id) if concept_id else None,
                estimated_minutes=row.estimated_minutes,
                passive=declared.passive,
                title=row.title,
                available_depths=tuple(
                    key for key in (row.depth_variants or {}) if key in {"simplified", "expanded"}
                ),
                hints=hints,
                guided_questions=questions,
                scaffold_intensity=states.get(str(concept_id)),
            )
        )
    if sitting is not None:
        events = list(
            await session.scalars(
                select(SignalEvent)
                .where(
                    SignalEvent.student_id == actor.id,
                    SignalEvent.session_id == sitting.id,
                )
                .order_by(SignalEvent.timestamp)
            )
        )
        adaptations = [
            event
            for event in events
            if event.event_type
            in ADAPTATION_HISTORY_EVENT_TYPES
            - {
                SignalEventType.BREAK_SUGGESTED,
                SignalEventType.MODALITY_SUGGESTION_SHOWN,
                SignalEventType.MODALITY_SWITCH_OUTCOME,
            }
        ]
        shifts = [
            event
            for event in events
            if event.event_type
            in {
                SignalEventType.MODALITY_SUGGESTION_ACCEPTED,
                SignalEventType.MODALITY_MANUAL_SWITCH,
            }
        ]
        now = datetime.now(UTC)
        current = by_key.get(signals.current_segment_id or "")
        if in_lesson and current is None:
            raise HTTPException(404, detail="Lesson segment not found")
        entered = [
            event.timestamp
            for event in events
            if current
            and str(event.event_data.get("segmentId")) in {str(current.id), current.segment_key}
        ]
        elapsed = (
            max(0, int((now - (min(entered) if entered else sitting.started_at)).total_seconds()))
            if current and (entered or current == stored[0])
            else 0
        )
        if current is not None:
            delivery = dict(sitting.delivery_state or {})
            runtime = dict(delivery.get("runtime") or {})
            if runtime.get("segmentId") != str(current.id):
                started = sitting.started_at if current == stored[0] and not runtime else now
                runtime = {"segmentId": str(current.id), "enteredAt": started.isoformat()}
                sitting.delivery_state = {**delivery, "runtime": runtime}
            elapsed = max(
                0, int((now - datetime.fromisoformat(runtime["enteredAt"])).total_seconds())
            )
        attempts = list(
            await session.scalars(
                select(LessonQuestionAttempt)
                .where(
                    LessonQuestionAttempt.session_id == sitting.id,
                )
                .order_by(LessonQuestionAttempt.submitted_at.desc())
            )
        )
        errors = 0
        for attempt in attempts:
            if attempt.correct is not False:
                break
            errors += 1
        signals = replace(
            signals,
            available_modalities=tuple(
                ContentModality(value) for value in current.available_modalities
            )
            if current
            else (),
            consecutive_errors=errors,
            misconception_confirmed=repeated_near_miss(attempts),
            session_modality_shift_count=len(shifts),
            session_adaptation_count=len(adaptations),
            seconds_since_last_adaptation=max(
                0, int((now - adaptations[-1].timestamp).total_seconds())
            )
            if adaptations
            else None,
            current_segment_elapsed_seconds=elapsed,
            same_segment_suggestion_shown=any(
                event.event_type is SignalEventType.MODALITY_SUGGESTION_SHOWN
                and str(event.event_data.get("segmentId")) == signals.current_segment_id
                for event in events
            ),
            declined_modalities=tuple(
                dict.fromkeys(
                    ContentModality(event.event_data["suggestedModality"])
                    for event in events
                    if event.event_type is SignalEventType.MODALITY_SUGGESTION_DECLINED
                    and event.event_data.get("suggestedModality")
                    in {item.value for item in ContentModality}
                )
            ),
            session_decline_count=sum(
                event.event_type is SignalEventType.MODALITY_SUGGESTION_DECLINED for event in events
            ),
        )
    result = AdaptationRequest(
        student_id=actor.id,
        lesson_id=lesson.id,
        session_id=sitting.id if sitting else None,
        mode=AdaptationMode.IN_LESSON if in_lesson else AdaptationMode.LESSON_LOAD,
        segments=tuple(segments),
        signals=signals,
    )
    await session.commit()
    return result
