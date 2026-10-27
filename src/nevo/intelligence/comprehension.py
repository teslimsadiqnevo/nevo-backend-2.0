"""Server-owned in-lesson gates and source-backed re-teaching; never AI marking."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from nevo.api.casing import CAMEL_CONFIG
from nevo.api.lesson_contracts import checkpoint_payloads, depth_approved, student_modalities
from nevo.core.config import get_settings
from nevo.db.models.account import StudentClassEnrollment, User
from nevo.db.models.content import LessonSegment
from nevo.db.models.frontend_support import Notification
from nevo.db.models.product import LessonQuestionAttempt
from nevo.db.models.teacher_assignment import TeacherClassAssignment
from nevo.domain.accounts.vocabulary import NotificationCategory, NotificationType
from nevo.domain.intelligence.vocabulary import LessonContentType, ScaffoldingLevel


def comprehension_gate_enabled() -> bool:
    return get_settings().comprehension_gate_enabled


class TeachingRoute(BaseModel):
    model_config = CAMEL_CONFIG

    action: Literal[
        "format",
        "simplify",
        "simpler_presentation",
        "slower",
        "rechunk",
        "panel",
        "calculation_scaffold",
    ]
    label: str
    format: Literal["text", "audio", "visual", "interactive"] | None = None
    requires_choice: bool = True


class TeachingPresentation(BaseModel):
    model_config = CAMEL_CONFIG
    density: Literal["low"] = "low"
    items_per_screen: Literal[1] = 1
    pacing: Literal["slow"] = "slow"
    recheck_required: Literal[True] = True
    body: str | None = None
    scaffold_level: ScaffoldingLevel | None = None


class ReteachingResponse(BaseModel):
    model_config = CAMEL_CONFIG

    question_id: str
    segment_id: str
    available_routes: list[TeachingRoute]
    recommended_route: TeachingRoute
    presentation: TeachingPresentation
    screens: list[str]
    calculation_steps: list[dict[str, object]] = Field(default_factory=list)
    hint: str | None = None
    teacher_notified: bool = False
    break_available: bool = True


class ComprehensionGate(BaseModel):
    model_config = CAMEL_CONFIG

    required: bool = False
    can_advance: bool
    segment_id: str | None = None
    question_ids: list[str] = Field(default_factory=list)
    unresolved_question_ids: list[str] = Field(default_factory=list)
    reteaching: ReteachingResponse | None = None
    assessment_gates: bool = False
    teacher_override_allowed: bool = False


class ComprehensionPolicy(BaseModel):
    model_config = CAMEL_CONFIG
    in_lesson_checks_gate: bool = False
    assessment_gates: Literal[False] = False
    panel_completion_unlocks: Literal[False] = False
    attempt_limit: None = None
    leave_always_allowed: Literal[True] = True
    break_always_available: Literal[True] = True
    teacher_override_allowed: Literal[False] = False
    supported_pass_counts_as_independent: Literal[False] = False
    sync_order: Literal["answers_before_progress"] = "answers_before_progress"

    @classmethod
    def current(cls):
        return cls(in_lesson_checks_gate=comprehension_gate_enabled())


class BreakControlRequest(BaseModel):
    model_config = CAMEL_CONFIG
    action: Literal["start", "return", "stop_for_day"]
    break_type: Literal["micro", "movement", "consolidation", "full", "stop_for_day"] = "micro"


class BreakControlResponse(BaseModel):
    model_config = CAMEL_CONFIG
    session_id: str
    status: Literal["paused", "learning", "stopped"]
    resume_segment_id: str | None = None
    concept_carried_forward: bool = True
    can_advance: bool = False


def segment_questions(segment):
    """Invalid legacy questions stop publication/access, never form an impossible gate."""
    try:
        questions = checkpoint_payloads(
            segment.comprehension_checkpoints or [], segment_key=segment.segment_key, strict=True
        )
        calculation = segment.calculation_variant or {}
        for step in calculation.get("steps", []):
            if step.get("answer") is None:
                raise ValueError(f"Calculation step {step.get('stepId')} has no answer")
            questions.append({"id": str(step["stepId"]), "answerKey": step["answer"]})
        return questions
    except (ValueError, TypeError, KeyError) as error:
        raise HTTPException(
            409,
            detail={
                "code": "lesson_content_requires_review",
                "message": "This lesson needs its teacher's review before it can be used.",
            },
        ) from error


async def gate_for_position(session, sitting, position=None, *, complete=False):
    if not comprehension_gate_enabled():
        return ComprehensionGate(required=False, can_advance=True)
    rows = list(
        await session.scalars(
            select(LessonSegment)
            .where(LessonSegment.lesson_id == sitting.lesson_id)
            .order_by(LessonSegment.sequence_order)
        )
    )
    attempts = list(
        await session.scalars(
            select(LessonQuestionAttempt).where(
                LessonQuestionAttempt.student_id == sitting.student_id,
                LessonQuestionAttempt.lesson_id == sitting.lesson_id,
                LessonQuestionAttempt.source.in_(["checkpoint", "calculation"]),
                LessonQuestionAttempt.correct.is_(True),
            )
        )
    )
    passed = {(row.segment_id, row.question_id) for row in attempts}
    from nevo.api.lesson_review import approved_check_ids

    reviewed = await approved_check_ids(session, sitting.lesson_id)
    from nevo.intelligence.delivery_preferences import lesson_choices, segment_choice

    preferences = lesson_choices(sitting)
    current_depth = preferences.get("depth", "original")
    for index, row in enumerate(rows):
        if not complete and position is not None and index >= position:
            break
        questions = [
            question for question in segment_questions(row)
            if (str(row.id), str(question["id"])) in reviewed
            or str(question["id"]) in {
                str(step.get("stepId")) for step in (row.calculation_variant or {}).get("steps", [])
            }
        ]
        unresolved = [str(q["id"]) for q in questions if (row.id, str(q["id"])) not in passed]
        if unresolved:
            next_question_id = unresolved[0]
            state = (sitting.delivery_state or {}).get("reteaching", {}).get(str(row.id)) or {}
            return ComprehensionGate(
                required=True,
                can_advance=False,
                segment_id=str(row.id),
                question_ids=[next_question_id],
                unresolved_question_ids=[next_question_id],
                reteaching=current_teaching(
                    row,
                    state.get("response"),
                    current_depth,
                    segment_choice(sitting, row).get("modality"),
                )
                if state.get("questionId") in unresolved
                else None,
            )
    return ComprehensionGate(required=True, can_advance=True)


async def require_gate(session, sitting, position=None, *, complete=False):
    gate = await gate_for_position(session, sitting, position, complete=complete)
    if not gate.can_advance:
        raise HTTPException(
            409,
            detail={
                "code": "comprehension_check_required",
                "message": (
                    "Try this check again before the next part. You can pause or leave anytime."
                ),
                "gate": gate.model_dump(mode="json", by_alias=True),
            },
        )


async def require_next_question(session, sitting, segment, question_id):
    """When enabled, accept only the next authored check in the current section."""
    if not comprehension_gate_enabled():
        return
    from nevo.api.lesson_review import approved_check_ids

    reviewed = await approved_check_ids(session, sitting.lesson_id)
    passed = set(
        await session.scalars(
            select(LessonQuestionAttempt.question_id).where(
                LessonQuestionAttempt.session_id == sitting.id,
                LessonQuestionAttempt.segment_id == segment.id,
                LessonQuestionAttempt.source.in_(["checkpoint", "calculation"]),
                LessonQuestionAttempt.correct.is_(True),
            )
        )
    )
    expected = next(
        (str(item["id"]) for item in segment_questions(segment)
         if str(item["id"]) not in passed
         and ((str(segment.id), str(item["id"])) in reviewed
              or str(item["id"]) in {
                  str(step.get("stepId")) for step in (segment.calculation_variant or {}).get("steps", [])
              })),
        None,
    )
    if expected is not None and str(question_id) != expected:
        raise HTTPException(
            409,
            detail={
                "code": "comprehension_check_out_of_order",
                "message": "Complete this section's checks one at a time.",
                "expectedQuestionId": expected,
            },
        )


async def cursor_index(session, lesson_id, module_position, segment_position):
    """Validate and return the lesson-wide, zero-based section cursor."""
    rows = list(
        await session.scalars(
            select(LessonSegment)
            .where(LessonSegment.lesson_id == lesson_id)
            .order_by(LessonSegment.sequence_order)
        )
    )
    # modulePosition identifies the containing module for display; the saved
    # section cursor has always been lesson-wide, like LessonProgress and resume.
    if segment_position > len(rows):
        raise HTTPException(422, detail={"code": "invalid_lesson_position"})
    return segment_position


def teaching_routes(segment, current_format="text", current_depth="original", question=None):
    if segment.content_type == LessonContentType.CALCULATION:
        routes = [
            TeachingRoute(
                action="calculation_scaffold",
                label="Show more support in this step",
                requires_choice=False,
            ),
            TeachingRoute(action="slower", label="Take it more slowly", requires_choice=False),
        ]
        if any(
            str(step.get("stepId")) == str((question or {}).get("id"))
            for step in (segment.calculation_variant or {}).get("steps", [])
        ):
            routes.insert(1, TeachingRoute(
                action="simpler_presentation",
                label="Show one step at a time",
                requires_choice=False,
            ))
        return routes
    formats = student_modalities(segment)
    labels = {
        "visual": "Try it as a picture",
        "audio": "Try it as audio",
        "interactive": "Try the activity",
        "text": "Try it as text",
    }
    routes = [
        TeachingRoute(action="format", format=value, label=labels[value])
        for value in formats
        if value != current_format
    ]
    simplified = (segment.depth_variants or {}).get("simplified")
    if current_depth != "simplified" and depth_approved(simplified):
        routes.append(TeachingRoute(action="simplify", label="Try it simpler"))
    routes.extend(
        [
            TeachingRoute(action="simpler_presentation", label="Show fewer things at once"),
            TeachingRoute(action="slower", label="Take it more slowly"),
            TeachingRoute(action="rechunk", label="Try smaller parts"),
        ]
    )
    question = question or {}
    if (
        question.get("guidedStepsReviewStatus") == "approved"
        and question.get("guidedSteps")
    ):
        routes.append(TeachingRoute(action="panel", label="Work through it together"))
    return routes


def current_teaching(segment, response, current_depth="original", current_format=None):
    if not response:
        return None
    result = ReteachingResponse.model_validate(response)
    available = student_modalities(segment)
    current_format = current_format or (available[0] if available else "text")
    result.available_routes = [
        route
        for route in result.available_routes
        if route.action != "format"
        or (route.format in available and route.format != current_format)
    ]
    if current_depth == "simplified":
        result.available_routes = [
            route for route in result.available_routes if route.action != "simplify"
        ]
    if result.recommended_route not in result.available_routes:
        result.recommended_route = result.available_routes[0]
    return result


async def note_attempt(session, sitting, segment, attempt):
    """Advance the help ladder once per new marked miss, not once per polling request."""
    if attempt.source == "assessment":
        return
    delivery = dict(sitting.delivery_state or {})
    states = dict(delivery.get("reteaching") or {})
    state = dict(states.get(str(segment.id)) or {})
    supported = bool(
        attempt.hint_count
        or attempt.attempt_number > 1
        or (state.get("questionId") == attempt.question_id and state.get("misses"))
    )
    if attempt.source == "calculation":
        supported = supported or bool(
            await session.scalar(
                select(LessonQuestionAttempt.id)
                .where(
                    LessonQuestionAttempt.student_id == sitting.student_id,
                    LessonQuestionAttempt.session_id == sitting.id,
                    LessonQuestionAttempt.segment_id == segment.id,
                    LessonQuestionAttempt.source == "calculation",
                    LessonQuestionAttempt.correct.is_(False),
                )
                .limit(1)
            )
        )
    attempt.question_snapshot = {
        **attempt.question_snapshot,
        "supportStatus": "supported" if supported else "independent",
    }
    if attempt.correct is True:
        if state.get("questionId") == attempt.question_id:
            state["passed"] = True
        states[str(segment.id)] = state
    elif attempt.correct is False:
        if state.get("questionId") != attempt.question_id:
            state = {
                "questionId": attempt.question_id,
                "misses": 0,
                "firstMissAt": datetime.now(UTC).isoformat(),
            }
        misses = int(state.get("misses", 0)) + 1
        from nevo.intelligence.delivery_preferences import segment_choice

        available_formats = student_modalities(segment)
        choice = segment_choice(sitting, segment)
        current_format = choice.get(
            "modality", available_formats[0] if available_formats else "text"
        )
        routes = teaching_routes(
            segment,
            current_format,
            choice.get("depth", "original"),
            attempt.question_snapshot,
        )
        recommended = routes[(misses - 1) % len(routes)]
        question_snapshot = attempt.question_snapshot or {}
        screens = [
            str(step.get("prompt"))
            for step in question_snapshot.get("guidedSteps", [])
            if isinstance(step, dict) and step.get("prompt")
        ]
        if not screens and question_snapshot.get("prompt"):
            screens = [str(question_snapshot["prompt"])]
        # These are rendering settings over existing text, not invented lesson content.
        presentation = {
            "density": "low",
            "itemsPerScreen": 1,
            "pacing": "slow",
            "recheckRequired": True,
        }
        if segment.content_type == LessonContentType.CALCULATION:
            presentation["scaffoldLevel"] = ScaffoldingLevel.STRONG.value
            step = next(
                (
                    row for row in (segment.calculation_variant or {}).get("steps", [])
                    if str(row.get("stepId")) == attempt.question_id
                ),
                None,
            )
            calculation_steps = ([{
                "stepId": step["stepId"],
                "prompt": step["prompt"],
                "input": step.get("input"),
                "expectedInput": step.get("expectedInput"),
                "options": step.get("options") or [],
                "unit": step.get("unit"),
            }] if step else [])
            screens = []
        else:
            calculation_steps = []
        if recommended.action == "simplify":
            presentation["body"] = segment.depth_variants["simplified"]["body"]
        response = ReteachingResponse(
            question_id=attempt.question_id,
            segment_id=str(segment.id),
            available_routes=routes,
            recommended_route=recommended,
            presentation=presentation,
            screens=screens,
            calculation_steps=calculation_steps,
            hint=attempt.question_snapshot.get("hint") if misses >= 2 else None,
            teacher_notified=bool(state.get("teacherNotified")),
        )
        if misses > len(routes) and not state.get("teacherNotified"):
            response.teacher_notified = await notify_teacher(session, sitting)
            state["teacherNotified"] = response.teacher_notified
        state.update(
            {
                "misses": misses,
                "passed": False,
                "response": response.model_dump(mode="json", by_alias=True),
            }
        )
        states[str(segment.id)] = state
    sitting.delivery_state = {**delivery, "reteaching": states}


async def notify_teacher(session, sitting):
    student = await session.get(User, sitting.student_id)
    recipients = set(
        await session.scalars(
            select(TeacherClassAssignment.teacher_id)
            .join(
                StudentClassEnrollment,
                StudentClassEnrollment.class_id == TeacherClassAssignment.class_id,
            )
            .where(
                StudentClassEnrollment.student_id == sitting.student_id,
                TeacherClassAssignment.removed_at.is_(None),
                TeacherClassAssignment.school_id == student.school_id,
            )
        )
    )
    if not recipients:
        recipients = set(
            await session.scalars(
                select(User.id).where(
                    User.school_id == student.school_id,
                    User.status == "active",
                    User.role.in_(["senco_admin", "other_admin"]),
                )
            )
        )
    target = f"/teacher/students/{sitting.student_id}"
    for recipient in recipients:
        recipient_user = await session.get(User, recipient)
        if not recipient_user or recipient_user.status != "active":
            continue
        surface = "teacher" if recipient_user.role == "teacher" else "admin"
        target = f"/{surface}/students/{sitting.student_id}"
        exists = await session.scalar(
            select(Notification.id)
            .where(
                Notification.recipient_id == recipient,
                Notification.type == NotificationType.CONCEPT_SUPPORT_NEEDED.value,
                Notification.navigates_to == target,
                Notification.read.is_(False),
                Notification.archived_at.is_(None),
            )
            .limit(1)
        )
        if not exists:
            session.add(
                Notification(
                    recipient_id=recipient,
                    recipient_role=str(recipient_user.role),
                    type=NotificationType.CONCEPT_SUPPORT_NEEDED.value,
                    category=NotificationCategory.ATTENTION.value,
                    title="A learner needs another way into this idea",
                    description=(
                        f"{student.first_name or 'A learner'} has not yet passed a check "
                        "after repeated support offers and needs your help."
                    ),
                    navigates_to=target,
                )
            )
    return bool(recipients)
