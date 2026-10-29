import hashlib
import json
import logging
import secrets
from datetime import UTC, datetime, time, timedelta
from io import BytesIO
from typing import Annotated, Literal
from uuid import NAMESPACE_DNS, UUID, uuid4, uuid5
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, JsonValue, model_validator
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.access import accessible_lessons
from nevo.api.auth import OptionalPrincipalDependency, PrincipalDependency
from nevo.api.casing import CAMEL_CONFIG
from nevo.api.consent import StudentLearningConsent
from nevo.api.dependencies import DatabaseSession
from nevo.api.frontend_unblockers import (
    MAX_LESSON_UPLOAD_BYTES,
    _extract_text,
    _source_type,
    _title_from_filename,
)
from nevo.api.learning_support import holds_learning_support, require_learning_support_if_admin
from nevo.api.lesson_contracts import (
    calculation_for_delivery,
    checkpoint_payloads,
    depth_payloads,
    depth_reviewer_names,
    safety_reviewed_visual,
    student_activity,
    student_modalities,
)
from nevo.api.product_common import (
    actor_user,
    require_approved_lessons,
    require_class_access,
    require_school_actor,
    require_teacher_console_actor,
    require_student_access,
)
from nevo.api.response_models import (
    AssignmentCreatedResponse,
    AssignmentResponse,
    AssignmentUpdatedResponse,
    BatchUploadResponse,
    CamelResponse,
    ConnectionResponse,
    LessonDetailResponse,
    LessonProgressResponse,
    LessonQuestionAttemptResponse,
    LessonSessionResponse,
    LessonSummaryResponse,
    OfflineDownloadResponse,
    OfflineManifestResponse,
    OfflinePackage,
    StudentDashboardResponse,
    StudentProfileResponse,
    TeacherDashboardResponse,
    UploadConfirmedResponse,
    UploadCreatedResponse,
    UploadReasonCatalogueResponse,
    UploadRetryResponse,
    UploadStatusResponse,
    UploadStructureDocument,
    UploadStructureResponse,
)
from nevo.content_parsing.activity import activity_for_delivery
from nevo.content_parsing.chunks import reading_chunks, reading_groups
from nevo.content_parsing.entities import SourcePage
from nevo.content_parsing.failures import (
    UploadReasonCode,
    failure_code,
)
from nevo.content_parsing.modules import delivery_modules
from nevo.content_parsing.upload_reuse import (
    find_reusable_upload,
    record_reused_media,
    reuse_response,
    source_key,
)
from nevo.db.models.account import Class, School, StudentClassEnrollment, User
from nevo.db.models.attention_flag import AttentionFlag, InterventionRecommendation
from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.models.frontend_support import Concept, LessonAssignment, Message
from nevo.db.models.learner_profile import LearnerProfile
from nevo.db.models.mastery import StudentConceptScheduling
from nevo.db.models.product import (
    LessonModule,
    LessonProgress,
    LessonQuestionAttempt,
    OfflineDownload,
    PostLessonProcessing,
    StudentOnboardingGrant,
    UploadJob,
    UploadSourceBlob,
)
from nevo.db.models.signal_event import LessonSession, SignalEvent
from nevo.db.models.sso import SchoolSsoConfiguration
from nevo.domain.accounts.age_bands import band_for_year_group, coerce_band
from nevo.domain.accounts.vocabulary import SsoConnectionStatus, SsoProvider, UserRole
from nevo.domain.intelligence.vocabulary import (
    AssignmentStatus,
    ContentParseStatus,
    LessonScope,
    LessonSourceType,
    UploadStage,
)
from nevo.domain.signal_events.vocabulary import LessonCompletionStatus, SignalEventType
from nevo.intelligence.comprehension import (
    BreakControlRequest,
    BreakControlResponse,
    ComprehensionGate,
)
from nevo.intelligence.delivery_preferences import (
    LessonChoice,
    SegmentChoice,
    SegmentChoiceWrite,
    delivery_for_read,
    lesson_choices,
    save_choice,
    segment_choice,
)
from nevo.intelligence.learning_runtime import (
    apply_marked_attempt,
    ensure_onboarding,
    ensure_prerequisites,
)
from nevo.intelligence.session_delivery import delivery_snapshot
from nevo.learner_profiles.post_lesson_worker import enqueue_post_lesson
from nevo.sso.service import SsoService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["learning product"])
CONSENT_WITHDRAWN_RESPONSE = {
    403: {
        "description": (
            "consent_pending or consent_required unless processing consent is confirmed; "
            "consent_withdrawn for explicit withdrawal. No learning write is accepted."
        )
    },
    503: {"description": "consent_service_unavailable: processing fails closed"},
}
LessonUpload = Annotated[UploadFile, File()]
BatchLessonUpload = Annotated[list[UploadFile], File()]
UploadScope = Annotated[str, Form(pattern="^(lesson|unit|term)$")]
#: Imported rather than restated, so the two upload routes cannot drift
#: apart on what a teacher is allowed to send.
MAX_UPLOAD_BYTES = MAX_LESSON_UPLOAD_BYTES
MAX_BATCH_UPLOAD_FILES = 20
UploadSubject = Annotated[str | None, Form(max_length=120)]
StudentFilter = Annotated[UUID | None, Query(alias="studentId")]
#: Defaults to mine for a teacher and school for an administrator.
LessonScopeFilter = Annotated[LessonScope | None, Query()]
ClassFilter = Annotated[UUID | None, Query(alias="classId")]


class AssignmentPatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    due_at: datetime | None = Field(default=None, alias="dueAt")
    available_from: datetime | None = Field(default=None, alias="availableFrom")
    status: AssignmentStatus | None = Field(default=None)


class AssignmentCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    lesson_ids: list[UUID] = Field(alias="lessonIds", min_length=1, max_length=50)
    student_ids: list[UUID] = Field(
        default_factory=list,
        alias="studentIds",
        max_length=500,
    )
    class_id: UUID | None = Field(default=None, alias="classId")
    due_at: datetime | None = Field(default=None, alias="dueAt")
    available_from: datetime | None = Field(default=None, alias="availableFrom")
    note: str | None = Field(default=None, max_length=2_000)


class AssignmentCancelRequest(BaseModel):
    reason: Literal[
        "finished_with",
        "superseded",
        "duplicate",
        "housekeeping",
        "wrong_content",
        "wrong_class",
        "assigned_in_error",
    ]


class ProgressWrite(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_id: UUID = Field(alias="sessionId")
    assignment_id: UUID | None = Field(default=None, alias="assignmentId")
    #: Module ordinal is zero-based. segmentPosition is the zero-based index
    #: across the entire lesson, not within the module.
    module_position: int = Field(default=0, alias="modulePosition", ge=0)
    segment_position: int = Field(default=0, alias="segmentPosition", ge=0)
    #: How far into the after-lesson check the child got, when they left part
    #: way through one. A cursor like the two above, zero-based.
    #:
    #: Sent so a resumed check starts where it stopped. The attempts for the
    #: session are the record of what was answered; this is only the place in
    #: the list, which attempts cannot tell you because a skipped question
    #: leaves no attempt behind. Null when the child is not in a check.
    #: Ask B49.
    check_position: int | None = Field(default=None, alias="checkPosition", ge=0)
    status: LessonCompletionStatus
    #: Deprecated compatibility input. The server derives the actual state
    #: from the latest marked attempt for every problem.
    result_state: Literal["landed", "partly_landed", "nothing_landed", "not_attempted"] | None = (
        Field(default=None, alias="resultState")
    )


class LessonQuestionAttemptWrite(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_id: UUID = Field(alias="sessionId")
    question_id: str = Field(
        validation_alias=AliasChoices("problemId", "questionId", "question_id"),
        serialization_alias="problemId",
        min_length=1,
        max_length=160,
        description="The server-issued question/problem id. The server marks the answer.",
    )
    segment_id: UUID | None = Field(default=None, alias="segmentId")
    source: Literal["checkpoint", "assessment", "calculation"] = "checkpoint"
    answer: JsonValue
    client_attempt_id: UUID | None = Field(default=None, alias="clientAttemptId")
    response_time_ms: int | None = Field(
        default=None,
        alias="responseTimeMs",
        ge=0,
        le=3_600_000,
        description=(
            "Observed answer time in milliseconds. Missing or implausibly short "
            "timing cannot raise mastery."
        ),
    )
    hint_count: int = Field(default=0, alias="hintCount", ge=0, le=100)


class ClassCodeConnectionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    class_code: str | None = Field(default=None, alias="classCode", min_length=4, max_length=20)
    class_id: UUID | None = Field(default=None, alias="classId")
    school_code: str | None = Field(default=None, alias="schoolCode", min_length=2, max_length=50)

    @model_validator(mode="after")
    def identify_class(self) -> "ClassCodeConnectionRequest":
        if self.class_code or (self.class_id and self.school_code):
            return self
        raise ValueError("classCode or classId with schoolCode is required")


class UploadRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str = Field(min_length=1, max_length=255)
    filename: str = Field(min_length=1, max_length=255)
    scope: str = Field(default="lesson", pattern="^(lesson|unit|term)$")
    source_type: LessonSourceType = Field(alias="sourceType")
    source_text: str = Field(alias="sourceText", min_length=1)
    subject: str | None = Field(default=None, max_length=120)


class UploadStructureWrite(BaseModel):
    structure: UploadStructureDocument


class CommittedSegmentEdit(CamelResponse):
    id: UUID
    title: str | None = Field(default=None, max_length=255)


class CommittedModuleEdit(CamelResponse):
    id: UUID | None = None
    title: str = Field(min_length=1, max_length=255)
    segment_record_ids: list[UUID] = Field(min_length=1)
    recap: str | None = None
    preview: str | None = None


class CommittedLessonStructureWrite(CamelResponse):
    title: str = Field(min_length=1, max_length=255)
    segments: list[CommittedSegmentEdit] = Field(min_length=1)
    modules: list[CommittedModuleEdit] = Field(default_factory=list)


class CommittedLessonStructureResponse(CamelResponse):
    lesson_id: UUID
    title: str
    segments: list[CommittedSegmentEdit]
    modules: list[CommittedModuleEdit]


class CloudImportRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_type: Literal["google_drive", "onedrive"] = Field(alias="sourceType")
    file_id: str = Field(alias="fileId", min_length=1, max_length=500)
    drive_id: str | None = Field(default=None, alias="driveId", max_length=500)
    title: str | None = Field(default=None, max_length=255)
    scope: str = Field(default="lesson", pattern="^(lesson|unit|term)$")
    subject: str | None = Field(default=None, max_length=120)


class CloudImportProviderConfig(BaseModel):
    model_config = CAMEL_CONFIG

    source_type: Literal["google_drive", "onedrive"]
    configured: bool
    picker_ready: bool
    client_id: str | None = None
    reason: str | None = None


class CloudImportConfigResponse(BaseModel):
    model_config = CAMEL_CONFIG

    providers: list[CloudImportProviderConfig]


class CloudFileItemResponse(BaseModel):
    model_config = CAMEL_CONFIG

    file_id: str
    name: str
    content_type: str
    drive_id: str | None = None
    size_bytes: int | None = None
    modified_at: datetime | None = None


class CloudFileListResponse(BaseModel):
    model_config = CAMEL_CONFIG

    source_type: Literal["google_drive", "onedrive"]
    files: list[CloudFileItemResponse]


class E2eWriteFixturesResponse(BaseModel):
    model_config = CAMEL_CONFIG

    student_id: UUID
    class_id: UUID
    assignment_id: UUID
    assignable_lesson_id: UUID
    review_lesson_id: UUID
    review_segment_id: UUID
    thread_id: UUID
    flag_id: UUID
    recommendation_id: UUID
    reset: bool = False


class RetryPagesRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    page_numbers: list[int] = Field(alias="pageNumbers", min_length=1, max_length=100)


def _e2e_fixture_id(name: str) -> UUID:
    return uuid5(NAMESPACE_DNS, f"nevo-e2e-write:{name}")


async def _e2e_write_fixtures(
    *,
    principal: PrincipalDependency,
    session: DatabaseSession,
    reset: bool,
) -> E2eWriteFixturesResponse:
    actor = await require_school_actor(
        session,
        principal,
        roles={UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN},
    )
    school = await session.get(School, actor.school_id)
    if school is None or not school.name.casefold().startswith("e2e test academy"):
        raise HTTPException(status_code=404, detail="E2E fixtures are not available")
    student = await session.scalar(
        select(User).where(
            User.school_id == school.id,
            User.login_identifier == "NV-E2E000",
        )
    )
    if student is None:
        raise HTTPException(status_code=409, detail="Run the E2E fixture seed first")
    class_id = await session.scalar(
        select(StudentClassEnrollment.class_id)
        .where(StudentClassEnrollment.student_id == student.id)
        .order_by(StudentClassEnrollment.class_id)
    )
    if class_id is None:
        raise HTTPException(status_code=409, detail="The E2E learner has no class")

    ids = {
        "assignment": _e2e_fixture_id("assignment:cancel"),
        "assignable_lesson": _e2e_fixture_id("lesson:new-assignment"),
        "review_lesson": _e2e_fixture_id("lesson:review"),
        "review_segment": _e2e_fixture_id("segment:review"),
        "thread": _e2e_fixture_id("message-thread"),
        "flag": _e2e_fixture_id("attention-flag"),
        "recommendation": _e2e_fixture_id("recommendation"),
    }
    required = (
        await session.get(LessonAssignment, ids["assignment"]),
        await session.get(Lesson, ids["assignable_lesson"]),
        await session.get(Lesson, ids["review_lesson"]),
        await session.get(LessonSegment, ids["review_segment"]),
        await session.get(AttentionFlag, ids["flag"]),
        await session.get(InterventionRecommendation, ids["recommendation"]),
    )
    if any(item is None for item in required):
        raise HTTPException(status_code=409, detail="Run the E2E fixture seed first")
    if reset:
        assignment, _, review_lesson, review_segment, flag, recommendation = required
        assignment.status = AssignmentStatus.ASSIGNED.value
        assignment.cancellation_reason = None
        assignment.recall_withdrawn = False
        review_segment.needs_review = True
        review_segment.review_reasons = ["e2e approval fixture"]
        review_segment.approved_at = None
        review_segment.approved_by = None
        review_lesson.status = ContentParseStatus.COMPLETED_WITH_REVIEW
        review_lesson.review_segment_count = 1
        flag.acknowledged_at = None
        flag.acknowledged_by = None
        recommendation.lesson_id = _e2e_fixture_id("lesson:assignable")
        await session.execute(delete(Message).where(Message.thread_id == ids["thread"]))
        await session.execute(
            delete(LessonAssignment).where(
                LessonAssignment.lesson_id == ids["assignable_lesson"],
                LessonAssignment.student_id == student.id,
            )
        )
        await session.commit()
    return E2eWriteFixturesResponse(
        student_id=student.id,
        class_id=class_id,
        assignment_id=ids["assignment"],
        assignable_lesson_id=ids["assignable_lesson"],
        review_lesson_id=ids["review_lesson"],
        review_segment_id=ids["review_segment"],
        thread_id=ids["thread"],
        flag_id=ids["flag"],
        recommendation_id=ids["recommendation"],
        reset=reset,
    )


@router.get("/e2e/write-fixtures", response_model=E2eWriteFixturesResponse)
async def e2e_write_fixtures(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> E2eWriteFixturesResponse:
    return await _e2e_write_fixtures(principal=principal, session=session, reset=False)


@router.post("/e2e/write-fixtures/reset", response_model=E2eWriteFixturesResponse)
async def reset_e2e_write_fixtures(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> E2eWriteFixturesResponse:
    return await _e2e_write_fixtures(principal=principal, session=session, reset=True)


async def _unapproved_counts(session: DatabaseSession, lesson_ids: list[UUID]) -> dict[UUID, int]:
    """Sections a teacher has still not cleared, per lesson, in one query.

    The same count the assignment refusal reports. reviewSegmentCount counts
    what was ever flagged and never falls, so a lesson already read by seven
    children still said "Needs review" on its card.
    """

    if not lesson_ids:
        return {}
    rows = await session.execute(
        select(LessonSegment.lesson_id, func.count(LessonSegment.id))
        .where(
            LessonSegment.lesson_id.in_(lesson_ids),
            LessonSegment.needs_review.is_(True),
            LessonSegment.approved_at.is_(None),
        )
        .group_by(LessonSegment.lesson_id)
    )
    return {lesson_id: int(total) for lesson_id, total in rows}


def _lesson_summary(
    lesson: Lesson,
    *,
    assignment_count: int = 0,
    author_names: dict[UUID, str] | None = None,
    unapproved_segment_count: int = 0,
    review_complete: bool = False,
) -> dict[str, object]:
    return {
        "id": str(lesson.id),
        "title": lesson.title,
        "description": lesson.description,
        "status": lesson.status.value,
        "sourceType": lesson.source_type.value,
        "segmentCount": lesson.segment_count,
        "reviewSegmentCount": lesson.review_segment_count,
        "subject": lesson.subject,
        "assignmentCount": assignment_count,
        "reviewComplete": review_complete,
        "estimatedMinutes": lesson.estimated_minutes,
        "createdById": str(lesson.created_by_user_id) if lesson.created_by_user_id else None,
        "createdByName": (author_names or {}).get(lesson.created_by_user_id),
        "unapprovedSegmentCount": unapproved_segment_count,
        "failureReason": lesson.failure_reason,
        "incidentId": lesson.incident_id,
        "createdAt": lesson.created_at,
    }


def _normalise_answer(value: JsonValue) -> object:
    if isinstance(value, str):
        return value.strip().casefold()
    if isinstance(value, list):
        return sorted((_normalise_answer(item) for item in value), key=repr)
    if isinstance(value, dict):
        return {key: _normalise_answer(item) for key, item in sorted(value.items())}
    return value


def _attempt_payload(item: LessonQuestionAttempt) -> dict[str, object]:
    return {
        "id": str(item.id),
        "lessonId": str(item.lesson_id),
        "sessionId": str(item.session_id),
        "questionId": item.question_id,
        "segmentId": str(item.segment_id) if item.segment_id else None,
        "source": item.source,
        "attemptNumber": item.attempt_number,
        "question": item.question_snapshot,
        "answer": item.answer,
        "correct": item.correct,
        "submittedAt": item.submitted_at,
    }


async def _attempt_payload_with_outcome(
    session: DatabaseSession, item: LessonQuestionAttempt
) -> dict[str, object]:
    payload = _attempt_payload(item)
    payload["resultState"] = await _derive_result_state(session, item.session_id)
    prompts, deadline = await _socratic_handoff(session, item)
    payload["handoffTo"] = "socratic_panel" if prompts else None
    payload["guidedPrompts"] = prompts
    from nevo.intelligence.comprehension import comprehension_gate_enabled

    payload["advanceAfterHandoff"] = bool(prompts) and not comprehension_gate_enabled()
    payload["handoffAvailableAt"] = deadline
    from nevo.intelligence.comprehension import gate_for_position

    sitting = await session.get(LessonSession, item.session_id)
    if sitting:
        segment = await session.get(LessonSegment, item.segment_id) if item.segment_id else None
        reteaching = (
            (sitting.delivery_state or {}).get("reteaching", {}).get(str(item.segment_id), {})
            if item.segment_id else {}
        )
        payload["reteaching"] = (
            reteaching.get("response")
            if item.correct is False and reteaching.get("questionId") == item.question_id
            else None
        )
        gate = await gate_for_position(
            session,
            sitting,
            segment.sequence_order if segment else None,
            complete=segment is None,
        )
        payload["comprehensionGate"] = gate.model_dump(mode="json", by_alias=True)
    payload["supportStatus"] = item.question_snapshot.get(
        "supportStatus",
        "supported" if item.hint_count or item.attempt_number > 1 else "independent",
    )
    return payload


async def _derive_result_state(
    session: DatabaseSession, session_id: UUID
) -> Literal["landed", "partly_landed", "nothing_landed", "not_attempted"]:
    """Judge a sitting from the latest server-marked answer per problem."""

    attempts = list(
        await session.scalars(
            select(LessonQuestionAttempt)
            .where(LessonQuestionAttempt.session_id == session_id)
            .order_by(
                LessonQuestionAttempt.question_id,
                LessonQuestionAttempt.attempt_number.desc(),
                LessonQuestionAttempt.submitted_at.desc(),
            )
        )
    )
    latest: dict[str, bool | None] = {}
    for attempt in attempts:
        latest.setdefault(attempt.question_id, attempt.correct)
    marked = [value for value in latest.values() if value is not None]
    if not marked:
        return "not_attempted"
    right = sum(value is True for value in marked)
    if right == len(marked):
        return "landed"
    if right == 0:
        return "nothing_landed"
    return "partly_landed"


async def _socratic_handoff(
    session: DatabaseSession, item: LessonQuestionAttempt
) -> tuple[list[dict[str, str]], datetime | None]:
    """Return the server-owned SCRUM-241 hand-off after three misses."""

    if item.source == "calculation":
        return [], None

    recent = list(
        await session.scalars(
            select(LessonQuestionAttempt)
            .where(
                LessonQuestionAttempt.session_id == item.session_id,
                LessonQuestionAttempt.question_id == item.question_id,
            )
            .order_by(LessonQuestionAttempt.attempt_number.desc())
            .limit(100)
        )
    )
    from nevo.intelligence.question_support import guidance_deadline

    student = await session.get(User, item.student_id)
    deadline = guidance_deadline(recent, student) if student else None
    if deadline is None or datetime.now(UTC) < deadline:
        return [], deadline
    if item.question_snapshot.get("guidedStepsReviewStatus") != "approved":
        return [], deadline
    guided = item.question_snapshot.get("guidedSteps") or []
    return [
        {
            "id": step["id"],
            "prompt": step["prompt"],
            "answerType": step["answerType"],
            "options": step.get("options") or [],
        }
        for step in guided
    ], deadline


def _tap_answer(step):
    count = step.get("tapCount")
    if count is None:
        value = step.get("answer")
        try:
            count = int(str(value).strip())
        except (TypeError, ValueError) as error:
            raise HTTPException(409, detail={"code": "calculation_step_unmarkable"}) from error
        if str(count) != str(value).strip():
            raise HTTPException(409, detail={"code": "calculation_step_unmarkable"})
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise HTTPException(409, detail={"code": "calculation_step_unmarkable"})
    return count


async def _question_for_attempt(
    session: DatabaseSession,
    lesson: Lesson,
    payload: LessonQuestionAttemptWrite,
    presentation_seed: str = "lesson",
) -> tuple[dict[str, object], UUID | None]:
    if payload.source == "assessment":
        questions = checkpoint_payloads(
            lesson.assessment or [],
            segment_key="lesson-assessment",
            presentation_seed=presentation_seed,
        )
        segment_id = None
    else:
        if payload.segment_id is None:
            raise HTTPException(status_code=422, detail="segmentId is required for a checkpoint")
        segment = await session.get(LessonSegment, payload.segment_id)
        if segment is None or segment.lesson_id != lesson.id:
            raise HTTPException(status_code=404, detail="Lesson question not found")
        if payload.source == "calculation":
            variant = segment.calculation_variant or {}
            concept_id = segment.concept_id or variant.get("conceptId")
            questions = [
                {
                    "id": str(step.get("stepId")),
                    "prompt": str(step.get("prompt") or ""),
                    "answerKey": _tap_answer(step) if step.get("input") == "tap" else step.get("answer"),
                    "acceptedAnswers": [] if step.get("input") == "tap" else step.get("acceptedAnswers") or step.get("accepted") or [],
                    "options": step.get("options") or [],
                    "hint": step.get("hint"),
                    "conceptId": str(concept_id) if concept_id else None,
                    "answerType": "numeric"
                    if step.get("input") == "tap" or isinstance(step.get("answer"), int | float)
                    else "expression" if any(symbol in str(step.get("answer") or "") for symbol in "+-*/=×÷")
                    else "text",
                    "textDensity": 0.1,
                    "calculationComplete": False,
                }
                for step in variant.get("steps", [])
            ]
            questions.append(
                {
                    "id": str(segment.id),
                    "prompt": variant.get("expression")
                    or segment.title
                    or "Complete the calculation.",
                    "answerKey": variant.get("answer"),
                    "conceptId": str(concept_id) if concept_id else None,
                    "answerType": "expression" if any(symbol in str(variant.get("answer") or "") for symbol in "+-*/=×÷") else "text",
                    "textDensity": 0.1,
                    "calculationComplete": True,
                }
            )
        else:
            questions = checkpoint_payloads(
                segment.comprehension_checkpoints,
                segment_key=segment.segment_key,
                concept_id=segment.concept_id,
                presentation_seed=presentation_seed,
            )
        segment_id = segment.id
    question = next(
        (item for item in questions if str(item.get("id")) == payload.question_id),
        None,
    )
    if question is None:
        raise HTTPException(status_code=404, detail="Lesson question not found")
    if not question.get("conceptId"):
        concepts = list(
            await session.scalars(
                select(Concept).where(
                    Concept.school_id == lesson.school_id,
                    Concept.lesson_id == lesson.id,
                )
            )
        )
        named = next(
            (
                item
                for item in concepts
                if item.name.casefold() == str(question.get("conceptName", "")).casefold()
            ),
            None,
        )
        bound = named or (concepts[0] if len(concepts) == 1 else None)
        if bound is not None:
            question = {**question, "conceptId": str(bound.id), "conceptName": bound.name}
    return question, segment_id


async def _classes_for_lesson(session: DatabaseSession, lesson_id: UUID) -> list[dict[str, object]]:
    """Every class this lesson reached, with how many children hold it.

    One query. The screen shows all of them rather than one, and the only
    other way to build it was a request per class across the teacher's own
    list, filtered to those with somebody assigned.
    """

    rows = await session.execute(
        select(
            Class.id,
            Class.name,
            Class.year_group,
            func.count(func.distinct(LessonAssignment.student_id)),
        )
        .join(Class, Class.id == LessonAssignment.class_id)
        .where(
            LessonAssignment.lesson_id == lesson_id,
            LessonAssignment.status != "cancelled",
        )
        .group_by(Class.id, Class.name, Class.year_group)
        .order_by(Class.name)
    )
    return [
        {
            "id": str(class_id),
            "name": name,
            "yearGroup": year_group,
            "studentCount": int(student_count or 0),
        }
        for class_id, name, year_group, student_count in rows
    ]


async def _lesson_for_actor(
    lesson_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> tuple[User, Lesson]:
    actor = await actor_user(session, principal)
    lesson = await session.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="Lesson not found")
    if actor.role == UserRole.STUDENT:
        assignment = await session.scalar(
            select(LessonAssignment.id).where(
                LessonAssignment.student_id == actor.id,
                LessonAssignment.lesson_id == lesson.id,
                LessonAssignment.status != "cancelled",
                or_(
                    LessonAssignment.available_from.is_(None),
                    LessonAssignment.available_from <= datetime.now(UTC),
                ),
            )
        )
        if assignment is None:
            raise HTTPException(status_code=404, detail="Lesson not found")
        if lesson.status == "failed":
            raise HTTPException(
                409,
                detail={
                    "code": "lesson_content_requires_review",
                    "message": "This lesson needs your teacher's review before it can be opened.",
                },
            )
        from nevo.intelligence.learning_runtime import ONBOARDING_MODULES, onboarding_modules

        if not set(ONBOARDING_MODULES).issubset(onboarding_modules(actor.baseline_profile or {})):
            actor.baseline_profile = {
                **(actor.baseline_profile or {}),
                "onboarding_return_lesson_id": str(lesson_id),
            }
            await session.commit()
        await ensure_onboarding(session, actor)
    elif actor.school_id != lesson.school_id:
        raise HTTPException(status_code=404, detail="Lesson not found")
    return actor, lesson


@router.get("/lessons", response_model=list[LessonSummaryResponse])
async def lessons(
    principal: PrincipalDependency,
    session: DatabaseSession,
    scope: LessonScopeFilter = None,
) -> list[dict[str, object]]:
    actor = await require_school_actor(session, principal)
    rows = await accessible_lessons(session, actor, scope=scope)
    counts = dict(
        (
            await session.execute(
                select(LessonAssignment.lesson_id, func.count(LessonAssignment.id))
                .where(
                    LessonAssignment.lesson_id.in_([item.id for item in rows]),
                    LessonAssignment.status != "cancelled",
                )
                .group_by(LessonAssignment.lesson_id)
            )
        ).all()
    )
    authors = await _author_names(session, rows)
    outstanding = await _unapproved_counts(session, [item.id for item in rows])
    from nevo.api.lesson_review import review_complete_map

    review_complete = await review_complete_map(session, [item.id for item in rows])
    return [
        _lesson_summary(
            item,
            assignment_count=int(counts.get(item.id, 0)),
            author_names=authors,
            unapproved_segment_count=outstanding.get(item.id, 0),
            review_complete=review_complete.get(item.id, False),
        )
        for item in rows
    ]


async def _author_names(session: DatabaseSession, lessons: list[Lesson]) -> dict[UUID, str]:
    """One query for every author, rather than one per lesson."""
    ids = {lesson.created_by_user_id for lesson in lessons if lesson.created_by_user_id}
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(User.id, User.first_name, User.last_name).where(User.id.in_(ids))
        )
    ).all()
    return {
        user_id: " ".join(part for part in (first, last) if part).strip() or "Unknown"
        for user_id, first, last in rows
    }


@router.get(
    "/lessons/{lesson_id}",
    response_model=LessonDetailResponse,
    responses=CONSENT_WITHDRAWN_RESPONSE,
)
async def lesson_detail(
    lesson_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
    consent: StudentLearningConsent = None,
) -> dict[str, object]:
    actor, lesson = await _lesson_for_actor(lesson_id, principal, session)
    # A child's device has no use for a teacher's review state, and sending it
    # anywhere it is not needed is how it ends up rendered somewhere it should
    # not be. One route serves both, so it is omitted rather than removed.
    for_teacher = actor.role is not UserRole.STUDENT
    from nevo.intelligence.session_delivery import lesson_delivery_config

    reading_config = (
        await lesson_delivery_config(session, actor, lesson_id) if not for_teacher else {}
    )
    segments = (
        await session.scalars(
            select(LessonSegment)
            .where(LessonSegment.lesson_id == lesson.id)
            .order_by(LessonSegment.sequence_order)
        )
    ).all()
    modules = (
        await session.scalars(
            select(LessonModule)
            .where(LessonModule.lesson_id == lesson.id)
            .order_by(LessonModule.sequence_order)
        )
    ).all()
    assignment_count = await session.scalar(
        select(func.count(LessonAssignment.id)).where(
            LessonAssignment.lesson_id == lesson.id,
            LessonAssignment.status != "cancelled",
        )
    )
    modules = delivery_modules(lesson.id, segments, modules)
    reviewer_names = (
        await depth_reviewer_names(session, segments, lesson.school_id) if for_teacher else {}
    )
    sitting = (
        None
        if for_teacher
        else await session.scalar(
            select(LessonSession)
            .where(
                LessonSession.student_id == actor.id,
                LessonSession.lesson_id == lesson_id,
                LessonSession.completion_status == LessonCompletionStatus.IN_PROGRESS,
                LessonSession.ended_at.is_(None),
            )
            .order_by(LessonSession.started_at.desc())
            .limit(1)
        )
    )
    recommendations = (sitting.delivery_state or {}).get("recommendations", {}) if sitting else {}
    from nevo.api.lesson_review import approved_check_ids

    reviewed_checks = await approved_check_ids(session, lesson.id)
    from nevo.api.lesson_review import _review_result
    review_complete = (await _review_result(session, lesson)).review_complete if for_teacher else False
    return {
        **_lesson_summary(
            lesson,
            assignment_count=int(assignment_count or 0),
            review_complete=review_complete,
            unapproved_segment_count=(await _unapproved_counts(session, [lesson.id])).get(
                lesson.id, 0
            ),
        ),
        "classes": await _classes_for_lesson(session, lesson.id),
        "confirmationSummary": lesson.confirmation_summary,
        "recap": lesson.recap,
        "assessment": checkpoint_payloads(
            lesson.assessment or [],
            segment_key="lesson-assessment",
            presentation_seed=str(actor.id),
        ),
        "segments": [
            {
                "id": str(item.id),
                "segmentKey": item.segment_key,
                "sequenceOrder": item.sequence_order,
                "contentType": item.content_type.value,
                "title": item.title,
                "body": item.body,
                "readingChunks": item.reading_chunks or reading_chunks(item.segment_key, item.body),
                "readingGroups": reading_groups(
                    item.reading_chunks or reading_chunks(item.segment_key, item.body),
                    reading_config,
                ),
                "availableModalities": item.available_modalities
                if for_teacher
                else student_modalities(item),
                "availableFormats": student_modalities(item),
                "primaryModality": segment_choice(sitting, item).get("modality"),
                "deliveryPreference": segment_choice(sitting, item) or None,
                "recommendedFormat": recommendations.get(str(item.id))
                if recommendations.get(str(item.id)) in student_modalities(item)
                else None,
                "comprehensionCheckpoints": checkpoint_payloads(
                    item.comprehension_checkpoints,
                    segment_key=item.segment_key,
                    presentation_seed=str(actor.id),
                    question_offset=item.sequence_order - 1,
                    include_pending_guidance=for_teacher,
                    reviewed_question_ids={qid for sid, qid in reviewed_checks if sid == str(item.id)},
                ),
                "textVariant": item.text_variant,
                "visualVariant": item.visual_variant
                if for_teacher
                else (
                    safety_reviewed_visual(item.visual_variant)
                    if "visual" in student_modalities(item)
                    else None
                ),
                "audioVariant": item.audio_variant,
                "interactiveVariant": activity_for_delivery(item.interactive_variant, item.body)
                if for_teacher
                else student_activity(item),
                **(
                    {"activityAvailability": {
                        "reachableByStudents": False,
                        "reason": "safety_instruction_not_rendered",
                    }}
                    if for_teacher
                    and isinstance(item.interactive_variant, dict)
                    and item.interactive_variant.get("steps")
                    and activity_for_delivery(item.interactive_variant, item.body).get("safety")
                    and student_activity(item) is None
                    else {}
                ),
                "calculationVariant": calculation_for_delivery(item.calculation_variant, for_teacher=for_teacher),
                "depthVariants": depth_payloads(
                    item.depth_variants,
                    item.text_variant,
                    for_student=not for_teacher,
                    reviewer_names=reviewer_names,
                ),
                **(
                    {
                        "needsReview": item.needs_review,
                        "reviewReasons": item.review_reasons,
                        "approved": item.approved_at is not None,
                        "approvedAt": item.approved_at,
                    }
                    if for_teacher
                    else {}
                ),
                "estimatedMinutes": item.estimated_minutes,
            }
            for item in segments
        ],
        "modules": [
            {
                "id": str(item.id),
                "title": item.title,
                "recap": item.recap,
                "preview": item.preview,
                "sequenceOrder": item.sequence_order,
                "segmentIds": item.segment_ids,
                "segmentRecordIds": [
                    str(segment.id)
                    for key in item.segment_ids
                    for segment in segments
                    if key in {segment.segment_key, str(segment.id)}
                ],
            }
            for item in modules
        ],
    }


@router.put(
    "/lessons/{lesson_id}/structure",
    response_model=CommittedLessonStructureResponse,
    responses={409: {"description": "lesson_structure_in_use"}},
)
async def edit_committed_lesson_structure(
    lesson_id: UUID,
    payload: CommittedLessonStructureWrite,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> CommittedLessonStructureResponse:
    actor = await require_school_actor(
        session, principal, roles={UserRole.TEACHER, UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}
    )
    lesson = await session.get(Lesson, lesson_id, with_for_update=True)
    if lesson is None or lesson.school_id != actor.school_id:
        raise HTTPException(404, detail={"code": "lesson_not_found"})
    if not payload.title.strip() or any(not item.title.strip() for item in payload.modules):
        raise HTTPException(422, detail={"code": "structure_title_required"})
    segments = list(await session.scalars(
        select(LessonSegment).where(LessonSegment.lesson_id == lesson_id)
        .order_by(LessonSegment.sequence_order).with_for_update()
    ))
    modules = list(await session.scalars(
        select(LessonModule).where(LessonModule.lesson_id == lesson_id)
        .order_by(LessonModule.sequence_order).with_for_update()
    ))
    by_segment = {item.id: item for item in segments}
    requested = [item.id for item in payload.segments]
    if len(requested) != len(by_segment) or set(requested) != set(by_segment):
        raise HTTPException(422, detail={"code": "structure_segments_mismatch"})
    known_modules = {item.id: item for item in modules}
    module_ids = [item.id for item in payload.modules if item.id is not None]
    if len(module_ids) != len(set(module_ids)) or not set(module_ids).issubset(known_modules):
        raise HTTPException(422, detail={"code": "structure_modules_mismatch"})
    ordered = [sid for module in payload.modules for sid in module.segment_record_ids]
    if payload.modules and (len(ordered) != len(requested) or set(ordered) != set(requested)):
        raise HTTPException(422, detail={"code": "structure_module_segments_mismatch"})
    if not payload.modules:
        ordered = requested
    current_membership = {item.id: item.module_id for item in segments}
    desired_membership = {
        sid: module.id for module in payload.modules for sid in module.segment_record_ids
    }
    structural_change = (
        ordered != [item.id for item in segments]
        or set(module_ids) != set(known_modules)
        or any(current_membership[sid] != desired_membership.get(sid) for sid in requested)
        or [item.id for item in modules] != module_ids
    )
    if structural_change and await session.scalar(
        select(LessonAssignment.id).where(
            LessonAssignment.lesson_id == lesson_id,
            LessonAssignment.status != "cancelled",
        ).limit(1)
    ):
        raise HTTPException(409, detail={"code": "lesson_structure_in_use"})
    lesson.title = payload.title.strip()
    for item in payload.segments:
        by_segment[item.id].title = item.title.strip() if item.title else None
    if structural_change:
        segment_offset = max((item.sequence_order for item in segments), default=0) + len(segments)
        for index, sid in enumerate(ordered, 1):
            by_segment[sid].sequence_order = segment_offset + index
            by_segment[sid].module_id = None
        module_offset = max((item.sequence_order for item in modules), default=0) + len(modules)
        for index, module in enumerate(modules, 1):
            module.sequence_order = module_offset + index
        await session.flush()
        for module in modules:
            if module.id not in module_ids:
                await session.delete(module)
        await session.flush()
        for index, item in enumerate(payload.modules, 1):
            module = known_modules.get(item.id)
            if module is None:
                module = LessonModule(id=uuid4(), lesson_id=lesson_id, title=item.title, sequence_order=index)
                session.add(module)
            module.sequence_order = index
            module.title = item.title.strip()
            module.recap = item.recap
            module.preview = item.preview
            module.segment_ids = [by_segment[sid].segment_key for sid in item.segment_record_ids]
            for sid in item.segment_record_ids:
                by_segment[sid].module_id = module.id
        for index, sid in enumerate(ordered, 1):
            by_segment[sid].sequence_order = index
    for item in payload.modules:
        module = known_modules.get(item.id)
        if module is not None:
            module.title = item.title.strip()
            module.recap = item.recap
            module.preview = item.preview
    await session.commit()
    saved_modules = list(await session.scalars(
        select(LessonModule).where(LessonModule.lesson_id == lesson_id)
        .order_by(LessonModule.sequence_order)
    ))
    return CommittedLessonStructureResponse(
        lessonId=lesson_id,
        title=lesson.title,
        segments=[CommittedSegmentEdit(id=sid, title=by_segment[sid].title) for sid in ordered],
        modules=[CommittedModuleEdit(
            id=module.id, title=module.title, recap=module.recap, preview=module.preview,
            segmentRecordIds=[by_segment[sid].id for sid in ordered if by_segment[sid].module_id == module.id],
        ) for module in saved_modules],
    )


@router.get("/assignments", response_model=list[AssignmentResponse])
async def assignments(
    principal: PrincipalDependency,
    session: DatabaseSession,
    student_id: StudentFilter = None,
    class_id: ClassFilter = None,
) -> list[dict[str, object]]:
    actor = await require_school_actor(session, principal)
    query = select(LessonAssignment, Lesson).join(Lesson, Lesson.id == LessonAssignment.lesson_id)
    if actor.role == UserRole.STUDENT:
        query = query.where(
            LessonAssignment.student_id == actor.id,
            or_(
                LessonAssignment.available_from.is_(None),
                LessonAssignment.available_from <= datetime.now(UTC),
            ),
        )
    else:
        query = query.where(Lesson.school_id == actor.school_id)
        if student_id:
            await require_student_access(session, principal, student_id)
            query = query.where(LessonAssignment.student_id == student_id)
        if class_id:
            await require_class_access(session, actor, class_id)
            query = query.where(LessonAssignment.class_id == class_id)
    rows = (await session.execute(query.order_by(LessonAssignment.assigned_at.desc()))).all()
    # One query for every assigning teacher on the page, not one per row.
    assigners = await _names_for(session, {item.teacher_id for item, _ in rows})
    return [
        {
            "id": str(item.id),
            "lesson": _lesson_summary(lesson),
            "studentId": str(item.student_id),
            "classId": str(item.class_id) if item.class_id else None,
            "status": item.status,
            "dueAt": item.due_at,
            "availableFrom": item.available_from,
            "note": item.note,
            "cancellationReason": item.cancellation_reason,
            "recallWithdrawn": item.recall_withdrawn,
            "assignedById": str(item.teacher_id) if item.teacher_id else None,
            "assignedByName": assigners.get(item.teacher_id),
            "assignedAt": item.assigned_at,
        }
        for item, lesson in rows
    ]


@router.get("/uploads/import-config", response_model=CloudImportConfigResponse)
async def cloud_import_config(
    principal: PrincipalDependency,
    session: DatabaseSession,
    request: Request,
) -> CloudImportConfigResponse:
    """Describe provider setup without pretending a browser picker exists."""
    actor = await require_school_actor(
        session,
        principal,
        roles={UserRole.TEACHER, UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN},
    )
    records = {
        item.provider: item
        for item in await session.scalars(
            select(SchoolSsoConfiguration).where(
                SchoolSsoConfiguration.school_id == actor.school_id
            )
        )
    }
    providers: list[CloudImportProviderConfig] = []
    sso = getattr(request.app.state, "sso_service", None)
    for provider, source_type in (
        (SsoProvider.GOOGLE, "google_drive"),
        (SsoProvider.MICROSOFT, "onedrive"),
    ):
        record = records.get(provider)
        configured = bool(
            record and record.enabled and record.connection_status is SsoConnectionStatus.CONNECTED
        )
        picker_ready = bool(
            configured
            and isinstance(sso, SsoService)
            and await sso.cloud_files_ready(school_id=actor.school_id, provider=provider)
        )
        providers.append(
            CloudImportProviderConfig(
                source_type=source_type,
                configured=configured,
                # Selection is served through /uploads/cloud-files, so the
                # browser never receives a provider token or client secret.
                picker_ready=picker_ready,
                client_id=record.client_id if record else None,
                reason=(
                    None
                    if picker_ready
                    else (
                        "Provider file access needs attention"
                        if configured
                        else "This provider is not connected for the school"
                    )
                ),
            )
        )
    return CloudImportConfigResponse(providers=providers)


@router.get("/uploads/cloud-files", response_model=CloudFileListResponse)
async def list_cloud_files(
    principal: PrincipalDependency,
    session: DatabaseSession,
    request: Request,
    source_type: Literal["google_drive", "onedrive"] = Query(alias="sourceType"),
    query: str | None = Query(default=None, max_length=120),
    drive_id: str | None = Query(default=None, alias="driveId", max_length=500),
    limit: int = Query(default=50, ge=1, le=100),
) -> CloudFileListResponse:
    actor = await require_school_actor(
        session,
        principal,
        roles={UserRole.TEACHER, UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN},
    )
    sso = getattr(request.app.state, "sso_service", None)
    if not isinstance(sso, SsoService):
        raise HTTPException(status_code=503, detail="Cloud import is unavailable")
    provider = SsoProvider.GOOGLE if source_type == "google_drive" else SsoProvider.MICROSOFT
    try:
        files = await sso.list_files(
            school_id=actor.school_id,
            provider=provider,
            query=query,
            drive_id=drive_id,
            limit=limit,
        )
    except LookupError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return CloudFileListResponse(
        source_type=source_type,
        files=[
            CloudFileItemResponse(
                file_id=item.file_id,
                name=item.name,
                content_type=item.content_type,
                drive_id=item.drive_id,
                size_bytes=item.size_bytes,
                modified_at=item.modified_at,
            )
            for item in files
        ],
    )


@router.post(
    "/assignments",
    response_model=AssignmentCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        # Documented because it is rendered. A client that has written copy
        # for lesson_not_approved is depending on this body, and an
        # undocumented refusal can change shape without anything failing.
        409: {
            "description": (
                "lesson_not_approved when a lesson still has segments a teacher "
                "has not cleared. detail.code is lesson_not_approved and "
                "detail.message names each lesson and what is outstanding on it."
            )
        },
    },
)
async def create_assignments(
    payload: AssignmentCreate,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    actor = await require_school_actor(
        session,
        principal,
        roles={UserRole.TEACHER, UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN},
    )
    student_ids = set(payload.student_ids)
    if payload.class_id:
        await require_class_access(session, actor, payload.class_id)
        class_students = await session.scalars(
            select(StudentClassEnrollment.student_id).where(
                StudentClassEnrollment.class_id == payload.class_id
            )
        )
        student_ids.update(class_students.all())
    if not student_ids:
        raise HTTPException(status_code=422, detail="At least one student is required")
    for student_id in student_ids:
        await require_student_access(session, principal, student_id)
    lessons_by_id = {
        item.id: item
        for item in (
            await session.scalars(select(Lesson).where(Lesson.id.in_(payload.lesson_ids)))
        ).all()
    }
    if len(lessons_by_id) != len(set(payload.lesson_ids)) or any(
        item.school_id != actor.school_id for item in lessons_by_id.values()
    ):
        raise HTTPException(status_code=404, detail="Lesson not found")
    await require_approved_lessons(session, lessons_by_id.keys())
    rows = [
        {
            "lesson_id": lesson_id,
            "student_id": student_id,
            "teacher_id": actor.id,
            "class_id": payload.class_id,
            "assignment_type": "class" if payload.class_id else "student",
            "due_at": payload.due_at,
            "available_from": payload.available_from,
            "note": payload.note,
        }
        for lesson_id in payload.lesson_ids
        for student_id in student_ids
    ]
    # Idempotent on (lesson, student, availableFrom): a client retrying a
    # partially failed fan-out re-sends rows that already landed, and those
    # must not become duplicates. Newly inserted ids come back from the
    # insert; the rest are read back, so the caller always receives the full
    # set of assignments its request is responsible for.
    inserted = (
        await session.scalars(
            insert(LessonAssignment)
            .values(rows)
            .on_conflict_do_nothing(
                index_elements=["lesson_id", "student_id", "available_from"],
            )
            .returning(LessonAssignment.id)
        )
    ).all()
    existing = (
        await session.scalars(
            select(LessonAssignment.id).where(
                LessonAssignment.lesson_id.in_(payload.lesson_ids),
                LessonAssignment.student_id.in_(student_ids),
                LessonAssignment.available_from.is_not_distinct_from(payload.available_from),
            )
        )
    ).all()
    await session.commit()
    return {
        "assignmentIds": [str(item) for item in existing],
        "createdCount": len(inserted),
        "duplicateCount": len(existing) - len(inserted),
    }


@router.patch("/assignments/{assignment_id}", response_model=AssignmentUpdatedResponse)
async def update_assignment(
    assignment_id: UUID,
    payload: AssignmentPatch,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    actor = await require_school_actor(
        session, principal, roles={UserRole.TEACHER, UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}
    )
    record = await session.get(LessonAssignment, assignment_id)
    lesson = await session.get(Lesson, record.lesson_id) if record else None
    if record is None or lesson is None or lesson.school_id != actor.school_id:
        raise HTTPException(status_code=404, detail="Assignment not found")
    if payload.due_at is not None:
        record.due_at = payload.due_at
    if payload.available_from is not None:
        record.available_from = payload.available_from
    if payload.status is not None:
        record.status = payload.status
    await session.commit()
    return {
        "id": str(record.id),
        "status": record.status,
        "dueAt": record.due_at,
        "availableFrom": record.available_from,
    }


@router.delete("/assignments/{assignment_id}", status_code=204)
async def cancel_assignment(
    assignment_id: UUID,
    payload: AssignmentCancelRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> None:
    actor = await require_school_actor(
        session, principal, roles={UserRole.TEACHER, UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}
    )
    record = await session.get(LessonAssignment, assignment_id)
    lesson = await session.get(Lesson, record.lesson_id) if record else None
    if record is None or lesson is None or lesson.school_id != actor.school_id:
        raise HTTPException(status_code=404, detail="Assignment not found")
    retraction = payload.reason in {"wrong_content", "wrong_class", "assigned_in_error"}
    record.status = AssignmentStatus.CANCELLED
    record.cancellation_reason = payload.reason
    record.recall_withdrawn = retraction
    if retraction:
        concept_ids = select(Concept.id).where(Concept.lesson_id == record.lesson_id)
        await session.execute(
            delete(StudentConceptScheduling).where(
                StudentConceptScheduling.student_id == record.student_id,
                StudentConceptScheduling.concept_id.in_(concept_ids),
            )
        )
    await session.commit()


@router.post(
    "/lessons/{lesson_id}/session",
    response_model=LessonSessionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        **CONSENT_WITHDRAWN_RESPONSE,
        409: {
            "description": (
                "onboarding_incomplete or prerequisite_required. "
                "Completed lessons retain completion and recover their review sitting."
            )
        },
    },
)
async def start_lesson_session(
    lesson_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
    consent: StudentLearningConsent = None,
) -> dict[str, object]:
    del consent
    actor, _ = await _lesson_for_actor(lesson_id, principal, session)
    if actor.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Student account required")
    await session.refresh(actor, with_for_update={"key_share": True})
    progress = await session.scalar(
        select(LessonProgress).where(
            LessonProgress.student_id == actor.id,
            LessonProgress.lesson_id == lesson_id,
        )
    )
    if progress is not None and (progress.status == "completed" or progress.completed_at):
        finished = await session.scalar(
            select(LessonSession)
            .where(
                LessonSession.student_id == actor.id,
                LessonSession.lesson_id == lesson_id,
                LessonSession.completion_status == LessonCompletionStatus.COMPLETED,
            )
            .order_by(LessonSession.ended_at.desc())
            .limit(1)
        )
        if finished is not None:
            progress.status = "completed"
            progress.session_id = finished.id
            await delivery_snapshot(session, actor, finished)
            await session.commit()
            return {
                "sessionId": str(finished.id),
                "resumed": True,
                "reviewMode": True,
                "reviewOfSessionId": str(finished.id),
                "completedAt": progress.completed_at or finished.ended_at,
                "depth": finished.delivery_depth,
                "reroutedFromSessionId": finished.rerouted_from_session_id,
                "deliveryState": delivery_for_read(finished),
                "segmentPosition": 0,
            }
        # Older signal snapshots could reopen the completed sitting. Recover
        # from the durable completion record, never from invented answers.
        finished = (
            await session.get(LessonSession, progress.session_id) if progress.session_id else None
        )
        if finished is not None and (
            finished.student_id != actor.id or finished.lesson_id != lesson_id
        ):
            finished = None
        completed_at = progress.completed_at or datetime.now(UTC)
        if finished is None:
            finished = LessonSession(
                id=uuid4(),
                student_id=actor.id,
                lesson_id=lesson_id,
                started_at=min(progress.started_at or completed_at, completed_at),
                ended_at=completed_at,
                completion_status=LessonCompletionStatus.COMPLETED,
                delivery_state={"reviewRecoveredFrom": "lesson_progress"},
            )
            session.add(finished)
        else:
            finished.completion_status = LessonCompletionStatus.COMPLETED
            finished.ended_at = max(completed_at, finished.started_at)
        progress.session_id = finished.id
        progress.status = "completed"
        await delivery_snapshot(session, actor, finished)
        await session.commit()
        return {
            "sessionId": str(finished.id),
            "resumed": True,
            "reviewMode": True,
            "reviewOfSessionId": str(finished.id),
            "completedAt": completed_at,
            "depth": finished.delivery_depth,
            "reroutedFromSessionId": finished.rerouted_from_session_id,
            "deliveryState": delivery_for_read(finished),
            "segmentPosition": 0,
        }
    await ensure_prerequisites(session, actor.id, lesson_id)
    existing = await session.scalar(
        select(LessonSession)
        .where(
            LessonSession.student_id == actor.id,
            LessonSession.lesson_id == lesson_id,
            LessonSession.completion_status == LessonCompletionStatus.IN_PROGRESS,
            LessonSession.ended_at.is_(None),
        )
        .order_by(LessonSession.started_at.desc())
    )
    if existing and (
        existing.started_at.date() != datetime.now(UTC).date()
        or datetime.now(UTC) - existing.started_at >= timedelta(hours=10)
    ):
        existing.completion_status = LessonCompletionStatus.EXITED
        existing.ended_at = datetime.now(UTC)
        existing = None
    if existing:
        await delivery_snapshot(session, actor, existing)
        await session.commit()
        return {
            "sessionId": str(existing.id),
            "resumed": True,
            "depth": existing.delivery_depth,
            "reroutedFromSessionId": existing.rerouted_from_session_id,
            "checkPosition": progress.check_position if progress else None,
            "checkResumableUntil": progress.check_resumable_until if progress else None,
            "deliveryState": delivery_for_read(existing),
            "segmentPosition": progress.segment_position if progress else 0,
        }
    if (
        progress is not None
        and progress.session_id is not None
        and progress.check_position is not None
        and progress.check_resumable_until is not None
        and progress.check_resumable_until >= datetime.now(UTC)
    ):
        check_session = await session.get(LessonSession, progress.session_id)
        if check_session is not None:
            await delivery_snapshot(session, actor, check_session)
            await session.commit()
            return {
                "sessionId": str(check_session.id),
                "resumed": True,
                "depth": check_session.delivery_depth,
                "reroutedFromSessionId": check_session.rerouted_from_session_id,
                "checkPosition": progress.check_position,
                "checkResumableUntil": progress.check_resumable_until,
                "deliveryState": delivery_for_read(check_session),
                "segmentPosition": progress.segment_position,
            }
    record = LessonSession(
        id=uuid4(),
        student_id=actor.id,
        lesson_id=lesson_id,
        started_at=datetime.now(UTC),
        completion_status=LessonCompletionStatus.IN_PROGRESS,
    )
    session.add(record)
    await delivery_snapshot(session, actor, record)
    if progress and progress.session_id:
        prior = await session.get(LessonSession, progress.session_id)
        if prior and prior.student_id == actor.id and prior.lesson_id == lesson_id:
            record.delivery_state = {
                **record.delivery_state,
                **{
                    key: value
                    for key, value in (prior.delivery_state or {}).items()
                    if key in {"reteaching", "guidedProgress", "hintedQuestions"}
                },
            }
    if progress is None:
        from nevo.intelligence.progression import next_work

        starting = await next_work(session, actor, lesson_id=lesson_id)
        progress = LessonProgress(
            student_id=actor.id,
            lesson_id=lesson_id,
            session_id=record.id,
            status="in_progress",
            segment_position=starting["segmentPosition"] if starting else 0,
            module_position=0,
            started_at=record.started_at,
        )
        session.add(progress)
    else:
        progress.session_id = record.id
        progress.status = "in_progress"
    await session.commit()
    return {
        "sessionId": str(record.id),
        "resumed": False,
        "depth": record.delivery_depth,
        "reroutedFromSessionId": record.rerouted_from_session_id,
        "deliveryState": delivery_for_read(record),
        "segmentPosition": progress.segment_position,
    }


@router.post(
    "/lessons/{lesson_id}/attempts",
    response_model=LessonQuestionAttemptResponse,
    status_code=status.HTTP_201_CREATED,
    responses=CONSENT_WITHDRAWN_RESPONSE,
)
async def save_lesson_question_attempt(
    lesson_id: UUID,
    payload: LessonQuestionAttemptWrite,
    principal: PrincipalDependency,
    session: DatabaseSession,
    consent: StudentLearningConsent = None,
) -> dict[str, object]:
    """Persist one answer attempt for later review.

    The question is resolved from the stored lesson and snapshotted beside the
    answer. Clients never submit an answer key or decide whether they were
    correct.
    """
    del consent
    actor, lesson = await _lesson_for_actor(lesson_id, principal, session)
    if actor.role is not UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Student account required")
    await session.refresh(actor, with_for_update={"key_share": True})
    lesson_session = await session.get(LessonSession, payload.session_id, with_for_update=True)
    if (
        lesson_session is None
        or lesson_session.student_id != actor.id
        or lesson_session.lesson_id != lesson.id
    ):
        raise HTTPException(status_code=404, detail="Lesson session not found")
    if payload.client_attempt_id is not None:
        existing = await session.scalar(
            select(LessonQuestionAttempt).where(
                LessonQuestionAttempt.client_attempt_id == payload.client_attempt_id,
                LessonQuestionAttempt.student_id == actor.id,
            )
        )
        if existing is not None:
            if (
                existing.lesson_id != lesson_id
                or existing.session_id != payload.session_id
                or existing.question_id != payload.question_id
                or _normalise_answer(existing.answer) != _normalise_answer(payload.answer)
            ):
                raise HTTPException(
                    409,
                    detail={
                        "code": "answer_attempt_conflict",
                        "message": "That attempt id belongs to a different answer.",
                    },
                )
            return await _attempt_payload_with_outcome(session, existing)
    question, segment_id = await _question_for_attempt(
        session, lesson, payload, presentation_seed=str(actor.id)
    )
    from nevo.intelligence.comprehension import (
        note_attempt,
        require_gate,
        require_next_question,
    )

    segment = await session.get(LessonSegment, segment_id) if segment_id else None
    if segment:
        await require_gate(session, lesson_session, segment.sequence_order - 1)
        if payload.source in {"checkpoint", "calculation"}:
            await require_next_question(session, lesson_session, segment, payload.question_id)
    else:
        await require_gate(session, lesson_session, complete=True)
    if question.get("answerKey") is None:
        raise HTTPException(
            409,
            detail={
                "code": "lesson_content_requires_review",
                "message": "This question needs its teacher's review.",
            },
        )
    if question.get("conceptId"):
        await ensure_prerequisites(session, actor.id, lesson.id, UUID(str(question["conceptId"])))
    attempt_number = int(
        await session.scalar(
            select(func.coalesce(func.max(LessonQuestionAttempt.attempt_number), 0) + 1).where(
                LessonQuestionAttempt.session_id == payload.session_id,
                LessonQuestionAttempt.question_id == payload.question_id,
            )
        )
        or 1
    )
    from nevo.content_parsing.answers import answer_matches

    record = LessonQuestionAttempt(
        student_id=actor.id,
        lesson_id=lesson.id,
        session_id=lesson_session.id,
        question_id=payload.question_id,
        segment_id=segment_id,
        source=payload.source,
        client_attempt_id=payload.client_attempt_id,
        attempt_number=attempt_number,
        question_snapshot=question,
        answer=payload.answer,
        correct=answer_matches(payload.answer, question),
        response_time_ms=payload.response_time_ms,
        hint_count=max(
            payload.hint_count,
            int(
                payload.question_id
                in (lesson_session.delivery_state or {}).get("hintedQuestions", [])
            ),
        ),
    )
    session.add(record)
    await session.flush()
    if segment:
        await note_attempt(session, lesson_session, segment, record)
    await apply_marked_attempt(session, actor, record)
    await session.commit()
    await session.refresh(record)
    return await _attempt_payload_with_outcome(session, record)


@router.get(
    "/lessons/{lesson_id}/sessions/{session_id}/comprehension", response_model=ComprehensionGate
)
async def lesson_comprehension_state(
    lesson_id: UUID,
    session_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
    consent: StudentLearningConsent = None,
):
    from nevo.intelligence.comprehension import gate_for_position

    actor, _ = await _lesson_for_actor(lesson_id, principal, session)
    sitting = await session.get(LessonSession, session_id)
    if (
        actor.role != UserRole.STUDENT
        or not sitting
        or (sitting.student_id != actor.id or sitting.lesson_id != lesson_id)
    ):
        raise HTTPException(404, detail="Lesson session not found")
    return await gate_for_position(session, sitting, complete=True)


@router.post(
    "/lessons/{lesson_id}/sessions/{session_id}/break", response_model=BreakControlResponse
)
async def control_lesson_break(
    lesson_id: UUID,
    session_id: UUID,
    payload: BreakControlRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
    consent: StudentLearningConsent = None,
):
    from nevo.db.models.signal_event import SignalEvent
    from nevo.intelligence.comprehension import gate_for_position

    actor, _ = await _lesson_for_actor(lesson_id, principal, session)
    if actor.role != UserRole.STUDENT:
        raise HTTPException(403, detail={"code": "student_account_required"})
    await session.refresh(actor, with_for_update={"key_share": True})
    sitting = await session.get(LessonSession, session_id, with_for_update=True)
    if not sitting or sitting.student_id != actor.id or sitting.lesson_id != lesson_id:
        raise HTTPException(404, detail="Lesson session not found")
    delivery = dict(sitting.delivery_state or {})
    current = delivery.get("breakControl") or {}
    if sitting.ended_at and not (
        payload.action == "stop_for_day" and current.get("status") == "stopped"
    ):
        raise HTTPException(409, detail={"code": "lesson_session_ended"})
    next_status = {"start": "paused", "return": "learning", "stop_for_day": "stopped"}[
        payload.action
    ]
    gate = await gate_for_position(session, sitting, complete=True)
    if current.get("status") != next_status:
        now = datetime.now(UTC)
        if payload.action == "return" and current.get("status") == "paused":
            event = SignalEventType.BREAK_END
        elif payload.action in {"start", "stop_for_day"}:
            event = SignalEventType.BREAK_START
            sitting.break_count = (sitting.break_count or 0) + 1
        else:
            event = None
        if event:
            session.add(
                SignalEvent(
                    student_id=actor.id,
                    session_id=sitting.id,
                    event_type=event,
                    timestamp=now,
                    event_data={
                        "breakType": "stop_for_day"
                        if payload.action == "stop_for_day"
                        else payload.break_type,
                        "trigger": "student_request",
                    },
                )
            )
        if payload.action == "stop_for_day":
            sitting.ended_at = now
            sitting.completion_status = LessonCompletionStatus.EXITED
            progress = await session.scalar(
                select(LessonProgress).where(
                    LessonProgress.student_id == actor.id, LessonProgress.lesson_id == lesson_id
                )
            )
            if progress and progress.status != "completed":
                progress.status = "exited"
        delivery.pop("breakOffer", None)
        delivery["breakControl"] = {"status": next_status, "at": now.isoformat()}
        sitting.delivery_state = delivery
        await session.commit()
    return BreakControlResponse(
        session_id=str(sitting.id),
        status=next_status,
        resume_segment_id=gate.segment_id,
        can_advance=gate.can_advance,
    )


@router.get(
    "/lessons/{lesson_id}/attempts",
    response_model=list[LessonQuestionAttemptResponse],
)
async def lesson_question_attempts(
    lesson_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
    session_id: Annotated[UUID | None, Query(alias="sessionId")] = None,
) -> list[dict[str, object]]:
    actor, lesson = await _lesson_for_actor(lesson_id, principal, session)
    if actor.role is not UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Student account required")
    query = select(LessonQuestionAttempt).where(
        LessonQuestionAttempt.student_id == actor.id,
        LessonQuestionAttempt.lesson_id == lesson.id,
    )
    if session_id is not None:
        query = query.where(LessonQuestionAttempt.session_id == session_id)
    records = (
        await session.scalars(
            query.order_by(
                LessonQuestionAttempt.submitted_at,
                LessonQuestionAttempt.attempt_number,
            )
        )
    ).all()
    return [await _attempt_payload_with_outcome(session, item) for item in records]


class SegmentChoiceResponse(SegmentChoice):
    lesson_preferences: LessonChoice = Field(
        default_factory=LessonChoice, alias="lessonPreferences"
    )
    available_formats: list[str] = Field(alias="availableFormats")
    recommended_format: str | None = Field(default=None, alias="recommendedFormat")


@router.put(
    "/lessons/{lesson_id}/sessions/{session_id}/segments/{segment_id}/preferences",
    response_model=SegmentChoiceResponse,
    responses={
        409: {"description": "format_unavailable, depth_unavailable or lesson_session_ended"}
    },
)
async def set_segment_preferences(
    lesson_id: UUID,
    session_id: UUID,
    segment_id: UUID,
    payload: SegmentChoiceWrite,
    principal: PrincipalDependency,
    session: DatabaseSession,
    consent: StudentLearningConsent = None,
):
    actor, _ = await _lesson_for_actor(lesson_id, principal, session)
    if actor.role != UserRole.STUDENT:
        raise HTTPException(403, detail={"code": "student_required"})
    sitting = await session.get(LessonSession, session_id, with_for_update=True)
    segment = await session.get(LessonSegment, segment_id)
    if (
        sitting is None
        or sitting.student_id != actor.id
        or sitting.lesson_id != lesson_id
        or segment is None
        or segment.lesson_id != lesson_id
    ):
        raise HTTPException(404, detail={"code": "lesson_session_not_found"})
    if sitting.ended_at or sitting.completion_status != LessonCompletionStatus.IN_PROGRESS:
        raise HTTPException(409, detail={"code": "lesson_session_ended"})
    available = student_modalities(segment)
    if payload.modality is not None and payload.modality not in available:
        raise HTTPException(409, detail={"code": "format_unavailable"})
    if payload.depth in {"simplified", "expanded"}:
        from nevo.api.lesson_contracts import depth_approved

        variant = (segment.depth_variants or {}).get(payload.depth)
        if not variant or not depth_approved(variant):
            raise HTTPException(409, detail={"code": "depth_unavailable"})
    previous = segment_choice(sitting, segment)
    await delivery_snapshot(session, actor, sitting)
    current = save_choice(sitting, segment, payload)
    if payload.modality is not None and payload.modality != previous.get("modality"):
        session.add(
            SignalEvent(
                id=uuid4(),
                student_id=actor.id,
                session_id=sitting.id,
                event_type=SignalEventType.MODALITY_MANUAL_SWITCH,
                timestamp=datetime.now(UTC),
                event_data={
                    "segmentId": str(segment.id),
                    "fromModality": previous.get("modality"),
                    "toModality": payload.modality,
                    "source": "student_control",
                },
            )
        )
    recommendation = (sitting.delivery_state or {}).get("recommendations", {}).get(str(segment.id))
    await session.commit()
    return {
        **current,
        "lessonPreferences": lesson_choices(sitting),
        "availableFormats": available,
        "recommendedFormat": recommendation if recommendation in available else None,
    }


@router.put(
    "/lessons/{lesson_id}/progress",
    response_model=LessonProgressResponse,
    responses=CONSENT_WITHDRAWN_RESPONSE,
)
async def save_lesson_progress(
    lesson_id: UUID,
    payload: ProgressWrite,
    principal: PrincipalDependency,
    session: DatabaseSession,
    request: Request,
    consent: StudentLearningConsent = None,
) -> dict[str, object]:
    del consent
    actor, _ = await _lesson_for_actor(lesson_id, principal, session)
    if actor.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Student account required")
    # FOR NO KEY UPDATE serializes saves without blocking the foreign-key
    # checks of concurrent adaptation decisions and signal writes.
    await session.refresh(actor, with_for_update={"key_share": True})
    lesson_session = await session.get(LessonSession, payload.session_id)
    if (
        lesson_session is None
        or lesson_session.student_id != actor.id
        or lesson_session.lesson_id != lesson_id
    ):
        raise HTTPException(status_code=404, detail="Lesson session not found")
    progress = await session.scalar(
        select(LessonProgress).where(
            LessonProgress.student_id == actor.id,
            LessonProgress.lesson_id == lesson_id,
        )
    )
    if payload.assignment_id is not None:
        assignment = await session.get(LessonAssignment, payload.assignment_id)
        if (
            assignment is None
            or assignment.student_id != actor.id
            or assignment.lesson_id != lesson_id
            or assignment.status == "cancelled"
        ):
            raise HTTPException(404, detail={"code": "assignment_not_found"})
    if progress is not None and (progress.status == "completed" or progress.completed_at):
        # A late player save or review visit must never undo a completed lesson.
        progress.status = "completed"
        outcome_session = progress.session_id or lesson_session.id
        job = await session.get(PostLessonProcessing, outcome_session)
        mastered, revisit = await _check_in_outcome(session, outcome_session)
        result = await _derive_result_state(session, outcome_session)
        await session.commit()
        return {
            "lessonId": str(lesson_id),
            "status": "completed",
            "modulePosition": progress.module_position,
            "segmentPosition": progress.segment_position,
            "intelligence": {"status": job.status if job else "not_run"},
            "resultState": result,
            "reroute": None,
            "masteredConcepts": mastered,
            "revisitConcepts": revisit,
            "resultNote": _result_note(mastered, revisit),
            "checkPosition": progress.check_position,
            "checkResumableUntil": progress.check_resumable_until,
        }
    from nevo.intelligence.comprehension import cursor_index, require_gate

    # Leaving and saving the current location always remain possible. Only
    # forward navigation and completion require the earlier in-lesson checks.
    if payload.status == "completed":
        await require_gate(session, lesson_session, complete=True)
    elif payload.check_position is not None:
        await require_gate(session, lesson_session, complete=True)
    elif payload.status == "in_progress" and (
        {"segment_position", "module_position"} & payload.model_fields_set
    ):
        index = await cursor_index(
            session,
            lesson_id,
            payload.module_position
            if "module_position" in payload.model_fields_set
            else progress.module_position
            if progress
            else 0,
            payload.segment_position
            if "segment_position" in payload.model_fields_set
            else progress.segment_position
            if progress
            else 0,
        )
        await require_gate(session, lesson_session, index)
    elif payload.status == "exited" and progress:
        # Leaving cannot become an alternate forward-navigation write.
        payload.module_position = progress.module_position
        payload.segment_position = progress.segment_position
    if progress is None:
        progress = LessonProgress(
            student_id=actor.id,
            lesson_id=lesson_id,
            module_position=payload.module_position,
            segment_position=payload.segment_position,
        )
        session.add(progress)
    progress.session_id = payload.session_id
    if "assignment_id" in payload.model_fields_set:
        progress.assignment_id = payload.assignment_id
    if "module_position" in payload.model_fields_set:
        progress.module_position = payload.module_position
    if "segment_position" in payload.model_fields_set:
        progress.segment_position = payload.segment_position
    if "check_position" in payload.model_fields_set:
        progress.check_position = payload.check_position
        progress.check_resumable_until = (
            _end_of_day() if payload.check_position is not None else None
        )
    progress.status = payload.status
    if payload.status is LessonCompletionStatus.IN_PROGRESS:
        target = await session.scalar(
            select(LessonSegment).where(
                LessonSegment.lesson_id == lesson_id,
                LessonSegment.sequence_order == progress.segment_position + 1,
            )
        )
        if target is not None and target.concept_id is not None:
            await ensure_prerequisites(session, actor.id, lesson_id, target.concept_id)
    progress.started_at = progress.started_at or lesson_session.started_at
    lesson_session.exit_position = str(progress.segment_position)
    derived_result = await _derive_result_state(session, lesson_session.id)
    # A lesson that was never attempted is not the "nothing landed" result.
    # Keep its sitting open at the saved cursor so the next launch resumes it.
    if payload.status in {"completed", "exited"}:
        lesson_session.ended_at = lesson_session.ended_at or datetime.now(UTC)
        lesson_session.completion_status = LessonCompletionStatus(payload.status)
    reroute: dict[str, object] | None = None
    if payload.status == "completed":
        from nevo.intelligence.learning_runtime import seed_completed_lesson_reviews

        await seed_completed_lesson_reviews(session, actor.id, lesson_session.id)
        progress.completed_at = datetime.now(UTC)
        assignment = (
            await session.get(LessonAssignment, payload.assignment_id)
            if payload.assignment_id
            else None
        )
        if assignment and assignment.student_id == actor.id:
            assignment.status = "completed"
            assignment.completed_at = datetime.now(UTC)
    # Final assessment measures outcomes; it cannot undo the in-lesson passes
    # or make completion conditional on the after-lesson score.
    intelligence: dict[str, object] = {"status": "not_run"}
    if payload.status == "completed":
        intelligence["status"] = await enqueue_post_lesson(
            session,
            session_id=lesson_session.id,
            student_id=actor.id,
            completed_at=lesson_session.ended_at,
        )
    mastered, revisit = await _check_in_outcome(session, lesson_session.id)
    await session.commit()
    return {
        "lessonId": str(lesson_id),
        "status": progress.status,
        "modulePosition": progress.module_position,
        "segmentPosition": progress.segment_position,
        "intelligence": intelligence,
        "resultState": derived_result,
        "reroute": reroute,
        "masteredConcepts": mastered,
        "revisitConcepts": revisit,
        "resultNote": _result_note(mastered, revisit),
        "checkPosition": progress.check_position,
        # A half-finished check is resumable for the rest of the day and no
        # longer. Stated rather than left to the client, so two tablets agree
        # on when it has lapsed. Ask B49.
        "checkResumableUntil": progress.check_resumable_until,
    }


def _end_of_day() -> datetime:
    """Midnight tonight, UTC. When a half-finished check stops resuming."""

    now = datetime.now(UTC)
    return datetime.combine(now.date(), time.max, tzinfo=UTC)


#: A concept counts as landed when the child got every question on it right.
#: Anything less is a revisit: "mostly right" on the idea the lesson was about
#: is not a reason to move on, and the child sees this sentence rather than a
#: score, so a near miss reading as a pass would be a lie told kindly.
async def _check_in_outcome(
    session: DatabaseSession, session_id: UUID
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Group this session's check-in answers by concept. Ask B26.

    These three fields were in the contract and nothing ever set them, so the
    "From the check-in" part of the result screen has only ever shown sample
    content. Mastery cannot be worked out on the client - it has neither the
    answer key nor the other attempts - so it comes from here.
    """

    rows = list(
        await session.scalars(
            select(LessonQuestionAttempt).where(
                LessonQuestionAttempt.session_id == session_id,
                LessonQuestionAttempt.source == "checkpoint",
            )
        )
    )
    grouped: dict[tuple[str | None, str], dict[str, int]] = {}
    for row in rows:
        snapshot = row.question_snapshot or {}
        concept_id = snapshot.get("conceptId")
        name = str(snapshot.get("conceptName") or "").strip()
        if not name:
            # No concept on the question, so nothing to attribute the answer
            # to. Counted nowhere rather than lumped under a made-up heading.
            continue
        key = (str(concept_id) if concept_id else None, name)
        tally = grouped.setdefault(key, {"asked": 0, "correct": 0})
        tally["asked"] += 1
        if row.correct:
            tally["correct"] += 1

    mastered: list[dict[str, object]] = []
    revisit: list[dict[str, object]] = []
    for (concept_id, name), tally in sorted(grouped.items(), key=lambda item: item[0][1]):
        outcome: dict[str, object] = {
            "conceptId": concept_id,
            "conceptName": name,
            "asked": tally["asked"],
            "correct": tally["correct"],
        }
        if tally["correct"] == tally["asked"]:
            mastered.append(outcome)
        else:
            revisit.append(outcome)
    return mastered, revisit


def _result_note(mastered: list[dict[str, object]], revisit: list[dict[str, object]]) -> str:
    """One sentence, derived from the lists so it cannot contradict them.

    Written to a child. It names what they have rather than what they lack,
    and where something needs another look it says so without ranking them
    against anybody.
    """

    if not mastered and not revisit:
        return ""
    kept = [str(item["conceptName"]) for item in mastered]
    again = [str(item["conceptName"]) for item in revisit]
    if kept and not again:
        return f"You explored {_join(kept)} today."
    if again and not kept:
        return f"{_join(again).capitalize()} is worth another look."
    return f"You explored {_join(kept)}. {_join(again).capitalize()} is worth another look."


def _join(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


@router.get("/students/me/dashboard", response_model=StudentDashboardResponse)
async def student_dashboard(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    actor = await actor_user(session, principal)
    if actor.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Student account required")
    from nevo.intelligence.learning_runtime import refresh_onboarding

    await refresh_onboarding(session, actor)
    await session.commit()
    enrolled_class = await session.scalar(
        select(Class)
        .join(StudentClassEnrollment, StudentClassEnrollment.class_id == Class.id)
        .where(
            StudentClassEnrollment.student_id == actor.id,
        )
        .order_by(StudentClassEnrollment.created_at)
        .limit(1)
    )
    age_band = coerce_band(actor.age_band, actor.date_of_birth) or band_for_year_group(
        enrolled_class.year_group if enrolled_class else None
    )
    items = await assignments(principal, session)
    due = [item for item in items if item["status"] != "completed"]
    progress = (
        await session.scalars(
            select(LessonProgress)
            .where(LessonProgress.student_id == actor.id)
            .order_by(LessonProgress.updated_at.desc())
        )
    ).all()
    recent = list(progress[:5])
    # One read for the five lessons rather than one each, so a library lesson
    # can appear under "Pick up where you left off" with its own name on it.
    # Asks B51 and B52.
    lessons = (
        {
            lesson.id: lesson
            for lesson in await session.scalars(
                select(Lesson).where(Lesson.id.in_([item.lesson_id for item in recent]))
            )
        }
        if recent
        else {}
    )
    outcomes: dict[UUID, tuple[list[dict[str, object]], list[dict[str, object]]]] = {}
    for item in recent:
        if item.session_id is not None:
            outcomes[item.session_id] = await _check_in_outcome(session, item.session_id)
    from nevo.intelligence.learning_runtime import ONBOARDING_MODULES, onboarding_modules
    from nevo.intelligence.progression import next_work

    ready = set(ONBOARDING_MODULES).issubset(onboarding_modules(actor.baseline_profile or {}))
    return {
        "onboardingComplete": ready,
        "nextWork": await next_work(session, actor) if ready else None,
        "student": {
            "id": str(actor.id),
            "firstName": actor.first_name,
            "ageBand": age_band,
        },
        "assignments": due,
        "recentProgress": [
            {
                "lessonId": str(item.lesson_id),
                "status": item.status,
                "segmentPosition": item.segment_position,
                "updatedAt": item.updated_at,
                "completedAt": item.completed_at,
                "title": (lesson.title if (lesson := lessons.get(item.lesson_id)) else ""),
                "subject": lesson.subject if lesson else None,
                # The denominator segmentPosition is counted against, so a
                # client can draw a fraction without inventing a total.
                "segmentCount": lesson.segment_count or 0 if lesson else 0,
                "checkPosition": item.check_position,
                "checkResumableUntil": item.check_resumable_until,
                "masteredConcepts": outcomes.get(item.session_id, ([], []))[0],
                "revisitConcepts": outcomes.get(item.session_id, ([], []))[1],
                "resultNote": _result_note(*outcomes.get(item.session_id, ([], []))),
            }
            for item in recent
        ],
    }


@router.get("/students/{student_id}/profile", response_model=StudentProfileResponse)
async def student_profile(
    student_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    actor = await require_student_access(session, principal, student_id)
    # The deepest per-child view in the product. Held deliberately, by
    # somebody, and refused here rather than by hiding a menu item.
    if actor.role is not UserRole.TEACHER:
        await require_learning_support_if_admin(session, actor)
    student = await session.get(User, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    profile = await session.scalar(
        select(LearnerProfile).where(LearnerProfile.learner_id == student_id)
    )
    flags = await session.scalar(
        select(func.count(AttentionFlag.id)).where(
            AttentionFlag.student_id == student_id,
            AttentionFlag.acknowledged_at.is_(None),
            AttentionFlag.resolved_at.is_(None),
        )
    )
    acknowledgements = []
    if await holds_learning_support(session, actor):
        from nevo.db.models.safety import ContentSafetyEvent

        rows = await session.execute(
            select(ContentSafetyEvent, User)
            .outerjoin(User, User.id == ContentSafetyEvent.acknowledged_by)
            .where(
                ContentSafetyEvent.student_id == student_id,
                ContentSafetyEvent.school_id == actor.school_id,
                ContentSafetyEvent.action.in_(["block", "safeguard"]),
                ContentSafetyEvent.acknowledged_at.is_not(None),
            )
            .order_by(ContentSafetyEvent.acknowledged_at.desc())
        )
        acknowledgements = [
            {
                "eventId": event.id,
                "acknowledgedAt": event.acknowledged_at,
                "acknowledgedBy": event.acknowledged_by,
                "acknowledgedByName": " ".join(
                    filter(None, (reviewer.first_name, reviewer.last_name))
                )
                if reviewer
                else None,
            }
            for event, reviewer in rows
        ]
    return {
        "student": {
            "id": str(student.id),
            "firstName": student.first_name,
            "lastName": student.last_name,
            # Derived where the stored value is absent or is a legacy age
            # string, so the dashboard can band the warm-up off this rather
            # than asking the child how old they are. Ask B5.
            "ageBand": coerce_band(student.age_band, student.date_of_birth),
        },
        "profile": (
            {
                "version": profile.version,
                "observedEventCount": profile.observed_event_count,
                "lastEvaluatedAt": profile.last_evaluated_at,
            }
            if profile
            else None
        ),
        "openFlagCount": flags or 0,
        "safeguardingAcknowledgements": acknowledgements,
    }


@router.get("/teachers/me/dashboard", response_model=TeacherDashboardResponse)
async def teacher_dashboard(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    actor = await require_teacher_console_actor(session, principal)
    class_query = select(Class).where(Class.school_id == actor.school_id)
    from nevo.db.models.teacher_assignment import TeacherClassAssignment
    class_query = class_query.join(TeacherClassAssignment).where(
            TeacherClassAssignment.teacher_id == actor.id,
            TeacherClassAssignment.removed_at.is_(None),
    )
    classes = (await session.scalars(class_query.distinct().order_by(Class.name))).all()
    return {
        "teacher": {"id": str(actor.id), "firstName": actor.first_name},
        "classes": [
            {"id": str(item.id), "name": item.name, "yearGroup": item.year_group}
            for item in classes
        ],
    }


@router.post(
    "/connections/class-code",
    response_model=ConnectionResponse,
    status_code=status.HTTP_201_CREATED,
    # Either, not neither: the handler takes an optional principal and
    # behaves differently signed in, so a flat [] told a client the one
    # thing it must not conclude - that sending a bearer changes nothing.
    openapi_extra={"security": [{"HTTPBearer": []}, {}]},
)
async def connect_by_class_code(
    payload: ClassCodeConnectionRequest,
    principal: OptionalPrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    query = select(Class)
    if payload.class_code:
        query = query.where(func.lower(Class.class_code) == payload.class_code.casefold())
    else:
        query = query.join(School, School.id == Class.school_id).where(
            Class.id == payload.class_id,
            func.lower(School.school_code) == (payload.school_code or "").casefold(),
        )
    school_class = await session.scalar(query.where(Class.archived_at.is_(None)))
    if school_class is None:
        raise HTTPException(status_code=404, detail="Class code not found")
    school = await session.get(School, school_class.school_id)
    if school is None:
        raise HTTPException(status_code=404, detail="School not found")

    if principal is None:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(minutes=20)
        session.add(
            StudentOnboardingGrant(
                school_id=school.id,
                class_id=school_class.id,
                token_digest=hashlib.sha256(token.encode()).hexdigest(),
                expires_at=expires_at,
            )
        )
        await session.commit()
        return {
            "classId": school_class.id,
            "status": "onboarding_ready",
            "schoolCode": school.school_code,
            "onboardingToken": token,
            "expiresAt": expires_at,
        }

    student = await actor_user(session, principal)
    if student.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Student account required")
    if school_class.school_id != student.school_id:
        raise HTTPException(status_code=404, detail="Class code not found")
    exists = await session.scalar(
        select(StudentClassEnrollment.id).where(
            StudentClassEnrollment.student_id == student.id,
            StudentClassEnrollment.class_id == school_class.id,
        )
    )
    if exists is None:
        session.add(StudentClassEnrollment(student_id=student.id, class_id=school_class.id))
    await session.commit()
    return {
        "classId": school_class.id,
        "status": "connected",
        "schoolCode": school.school_code,
    }


@router.get(
    "/lessons/{lesson_id}/offline-manifest",
    response_model=OfflineManifestResponse,
    responses=CONSENT_WITHDRAWN_RESPONSE,
)
async def read_offline_manifest(
    lesson_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
    consent: StudentLearningConsent = None,
) -> dict[str, object]:
    """What a lesson would cost to keep, without keeping it. Ask B61.

    The Downloads screen shows a size on every row, and the only place a size
    existed was the response to POST /download - which records a download. So
    a size could not be shown until the child had already committed to one.

    A read, so it records nothing. The size is measured from the archive this
    describes rather than estimated, which costs a build per call: that is
    why this is per lesson and not a field on the list. A client wanting
    sizes for a page of lessons should ask for the ones it is about to show.
    """

    del consent
    _actor, _lesson = await _lesson_for_actor(lesson_id, principal, session)
    package = await _offline_package_payload(session, lesson_id, _actor)
    archive = _offline_archive(package, lesson_id)
    return {
        "lessonId": str(lesson_id),
        "version": 1,
        "segmentCount": _segment_count(package),
        "generatedAt": datetime.now(UTC).isoformat(),
        "packageUrl": f"/api/v1/lessons/{lesson_id}/offline-package",
        "sizeBytes": len(archive),
        "files": ["lesson.json", "manifest.json"],
        "includesMedia": False,
    }


@router.get(
    "/lessons/{lesson_id}/offline-package.json",
    response_model=OfflinePackage,
    responses=CONSENT_WITHDRAWN_RESPONSE,
)
async def read_offline_package_json(
    lesson_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
    consent: StudentLearningConsent = None,
) -> dict[str, object]:
    """lesson.json on its own, so a client can check it without unzipping.

    The spec described the archive's contents as "the lesson package" and
    nothing more, so the app had to validate it by guessing - and guessing
    LessonDetailResponse would have rejected a correct package, because this
    is a narrower and differently shaped thing. Ask B60.

    The same payload the archive carries, from the same builder, so the two
    cannot drift.
    """

    del consent
    actor, _ = await _lesson_for_actor(lesson_id, principal, session)
    return await _offline_package_payload(session, lesson_id, actor)


@router.post(
    "/lessons/{lesson_id}/download",
    response_model=OfflineDownloadResponse,
    responses=CONSENT_WITHDRAWN_RESPONSE,
)
async def create_offline_download(
    lesson_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
    consent: StudentLearningConsent = None,
) -> dict[str, object]:
    del consent
    actor, _ = await _lesson_for_actor(lesson_id, principal, session)
    if actor.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Student account required")
    record = await session.scalar(
        select(OfflineDownload).where(
            OfflineDownload.student_id == actor.id,
            OfflineDownload.lesson_id == lesson_id,
        )
    )
    package = await _offline_package_payload(session, lesson_id, actor)
    # Built here as well as on the GET, because a size the Downloads screen
    # can show has to be measured rather than estimated, and the only honest
    # measure is the archive itself. Ask B31.
    archive = _offline_archive(package, lesson_id)
    manifest = {
        "lessonId": str(lesson_id),
        "version": 1,
        "segmentCount": _segment_count(package),
        "generatedAt": datetime.now(UTC).isoformat(),
        "packageUrl": f"/api/v1/lessons/{lesson_id}/offline-package",
        "sizeBytes": len(archive),
        "files": ["lesson.json", "manifest.json"],
        "includesMedia": False,
    }
    if record is None:
        record = OfflineDownload(
            student_id=actor.id,
            lesson_id=lesson_id,
            manifest=manifest,
        )
        session.add(record)
    else:
        record.manifest = manifest
    await session.commit()
    return {"id": str(record.id), "manifest": record.manifest}


def _segment_count(package: dict[str, object]) -> int:
    """How many segments the package holds, from an untyped payload."""

    segments = package.get("segments")
    return len(segments) if isinstance(segments, list) else 0


def _offline_archive(payload: dict[str, object], lesson_id: UUID) -> bytes:
    """The zip a client caches, built once and used by both routes.

    Two files: the lesson as JSON, and a manifest naming what is in the
    archive. Media is referenced rather than bundled, so this is the text of
    a lesson and not the whole of it - stated in the manifest so an offline
    client knows what it has.
    """

    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "lesson.json",
            json.dumps(payload, ensure_ascii=True, default=str, separators=(",", ":")),
        )
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "lessonId": str(lesson_id),
                    "version": 1,
                    "files": ["lesson.json", "manifest.json"],
                    "includesMedia": False,
                },
                separators=(",", ":"),
            ),
        )
    return output.getvalue()


@router.get(
    "/lessons/{lesson_id}/offline-package",
    # Declared so the spec says what this returns. It was showing an untyped
    # empty object, which is not something a client can cache against: it is
    # a zip, and the shape inside it is the lesson package. Ask B31.
    response_class=Response,
    responses={
        **CONSENT_WITHDRAWN_RESPONSE,
        200: {
            "description": (
                "A zip holding lesson.json (the lesson package) and "
                "manifest.json. Media is referenced by URL, not bundled."
            ),
            "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
        },
    },
)
async def offline_package(
    lesson_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
    consent: StudentLearningConsent = None,
) -> Response:
    actor, lesson = await _lesson_for_actor(lesson_id, principal, session)
    if actor.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Student account required")
    payload = await _offline_package_payload(session, lesson_id, actor)
    content = _offline_archive(payload, lesson.id)
    filename = f"nevo-lesson-{lesson.id}.zip"
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/uploads/text", response_model=UploadCreatedResponse, status_code=status.HTTP_201_CREATED
)
async def staged_upload(
    payload: UploadRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    actor = await require_school_actor(
        session, principal, roles={UserRole.TEACHER, UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}
    )
    return await _queue_upload(
        payload,
        actor=actor,
        session=session,
        source_content=payload.source_text.encode("utf-8"),
        content_type="text/plain; charset=utf-8",
        source_is_extracted_text=True,
    )


async def _queue_upload(
    payload: UploadRequest,
    *,
    actor: User,
    session: AsyncSession,
    source_content: bytes,
    content_type: str,
    source_is_extracted_text: bool,
) -> dict[str, object]:
    fingerprint = source_key(
        text=payload.source_text,
        title=payload.title,
        subject=payload.subject,
        source_type=payload.source_type.value,
        scope=payload.scope,
    )
    lock = int.from_bytes(
        hashlib.sha256(f"{actor.id}:{fingerprint}".encode()).digest()[:8], "big", signed=True
    )
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
    reused = await find_reusable_upload(
        session,
        actor_id=actor.id,
        school_id=actor.school_id,
        scope=payload.scope,
        key=fingerprint,
        subject=payload.subject,
    )
    if reused is not None:
        await record_reused_media(session, reused)
        return reuse_response(reused)
    pending = await session.scalar(
        select(UploadJob)
        .where(
            UploadJob.requested_by_id == actor.id,
            UploadJob.school_id == actor.school_id,
            UploadJob.scope == payload.scope,
            UploadJob.status == "processing",
            UploadJob.structure["sourceCacheKey"].astext == fingerprint,
        )
        .order_by(UploadJob.created_at.desc())
    )
    if pending is not None:
        return reuse_response(pending)
    job = UploadJob(
        school_id=actor.school_id,
        requested_by_id=actor.id,
        scope=payload.scope,
        filename=payload.filename,
        status="processing",
        stage=UploadStage.RECEIVING_FILE.value,
        structure={"sourceCacheKey": fingerprint},
    )
    session.add(job)
    await session.flush()
    session.add(
        UploadSourceBlob(
            upload_id=job.id,
            filename=payload.filename,
            content_type=content_type,
            content=source_content,
            parse_metadata={
                "title": payload.title,
                "sourceType": payload.source_type.value,
                "subject": payload.subject,
                "contentIsExtractedText": source_is_extracted_text,
            },
        )
    )
    await session.commit()
    logger.info(
        "Upload queued upload=%s bytes=%s source_type=%s",
        job.id,
        len(source_content),
        payload.source_type.value,
    )
    return {"uploadId": str(job.id), "status": job.status, "stage": job.stage}


@router.post("/uploads", response_model=UploadCreatedResponse, status_code=status.HTTP_201_CREATED)
async def staged_file_upload(
    principal: PrincipalDependency,
    session: DatabaseSession,
    file: LessonUpload,
    scope: UploadScope = "lesson",
    subject: UploadSubject = None,
) -> dict[str, object]:
    return await _ingest_one_file(
        file=file,
        filename=file.filename or "lesson.txt",
        scope=scope,
        subject=subject,
        principal=principal,
        session=session,
    )


async def _ingest_one_file(
    *,
    file: UploadFile,
    filename: str,
    scope: str,
    subject: str | None,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    """Parse one uploaded file into a staged upload job.

    Shared by the single-file and batch routes so both apply the same size
    limit, text extraction and source retention.
    """
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Lesson file exceeds 50 MB")
    try:
        source_text = _extract_text(filename, content)
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=400, detail="Could not read lesson file") from error
    if not source_text.strip():
        raise HTTPException(status_code=400, detail="No readable lesson text was found")
    actor = await require_school_actor(
        session, principal, roles={UserRole.TEACHER, UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}
    )
    reused = await find_reusable_upload(
        session,
        actor_id=actor.id,
        school_id=actor.school_id,
        scope=scope,
        content=content,
        subject=subject,
    )
    if reused is not None:
        await record_reused_media(session, reused)
        return reuse_response(reused)
    result = await _queue_upload(
        UploadRequest(
            title=_title_from_filename(filename),
            filename=filename,
            scope=scope,
            sourceType=_source_type(filename),
            sourceText=source_text,
            subject=subject,
        ),
        actor=actor,
        session=session,
        source_content=content,
        content_type=file.content_type or "application/octet-stream",
        source_is_extracted_text=False,
    )
    return result


@router.post(
    "/uploads/batch",
    response_model=BatchUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def staged_batch_upload(
    principal: PrincipalDependency,
    session: DatabaseSession,
    files: BatchLessonUpload,
    scope: UploadScope = "lesson",
    subject: UploadSubject = None,
) -> dict[str, object]:
    """Ingest several lesson files in one request.

    Each file is parsed independently and reports its own outcome. A file that
    is too large or has no readable text is rejected on its own line rather
    than failing the whole batch, so the picker never has to guess which of a
    dozen files landed.
    """
    if not files:
        raise HTTPException(status_code=422, detail="At least one file is required")
    if len(files) > MAX_BATCH_UPLOAD_FILES:
        raise HTTPException(
            status_code=422,
            detail=f"A batch is limited to {MAX_BATCH_UPLOAD_FILES} files",
        )
    results: list[dict[str, object]] = []
    for file in files:
        filename = file.filename or "lesson.txt"
        try:
            result = await _ingest_one_file(
                file=file,
                filename=filename,
                scope=scope,
                subject=subject,
                principal=principal,
                session=session,
            )
        except HTTPException as error:
            results.append(
                {
                    "filename": filename,
                    "accepted": False,
                    "error": str(error.detail),
                    "reasonCode": failure_code(str(error.detail)),
                }
            )
        else:
            results.append({"filename": filename, "accepted": True, **result})
    accepted = sum(1 for item in results if item["accepted"])
    return {
        "uploads": results,
        "acceptedCount": accepted,
        "rejectedCount": len(results) - accepted,
    }


@router.post(
    "/uploads/import",
    response_model=UploadCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_cloud_file(
    payload: CloudImportRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
    request: Request,
) -> dict[str, object]:
    actor = await require_school_actor(
        session,
        principal,
        roles={UserRole.TEACHER, UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN},
    )
    sso = getattr(request.app.state, "sso_service", None)
    if not isinstance(sso, SsoService):
        raise HTTPException(status_code=503, detail="Cloud import is unavailable")
    provider = (
        SsoProvider.GOOGLE if payload.source_type == "google_drive" else SsoProvider.MICROSOFT
    )
    try:
        cloud_file = await sso.download_file(
            school_id=actor.school_id,
            provider=provider,
            file_id=payload.file_id,
            drive_id=payload.drive_id,
        )
    except LookupError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if len(cloud_file.content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Cloud file exceeds 50 MB")
    source_text = _extract_text(cloud_file.filename, cloud_file.content)
    if not source_text.strip():
        raise HTTPException(status_code=400, detail="No readable lesson text was found")
    result = await _queue_upload(
        UploadRequest(
            title=payload.title or _title_from_filename(cloud_file.filename),
            filename=cloud_file.filename,
            scope=payload.scope,
            sourceType=LessonSourceType(payload.source_type),
            sourceText=source_text,
            subject=payload.subject,
        ),
        actor=actor,
        session=session,
        source_content=cloud_file.content,
        content_type=cloud_file.content_type,
        source_is_extracted_text=False,
    )
    if result.get("reused"):
        return result
    return result


@router.post(
    "/uploads/{upload_id}/retry-pages",
    response_model=UploadRetryResponse,
    responses={
        409: {"description": "upload_already_processing, or the source is not a PDF"},
        404: {"description": "The upload or retained source was not found"},
    },
)
async def retry_upload_pages(
    upload_id: UUID,
    payload: RetryPagesRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    actor = await require_school_actor(
        session,
        principal,
        roles={UserRole.TEACHER, UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN},
    )
    job = await session.get(UploadJob, upload_id)
    blob = await session.get(UploadSourceBlob, upload_id)
    if job is None or job.school_id != actor.school_id or blob is None:
        raise HTTPException(status_code=404, detail="Upload source was not found")
    if not blob.filename.casefold().endswith(".pdf"):
        raise HTTPException(status_code=409, detail="Page retry is available for PDF uploads")
    if job.status == "processing":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "upload_already_processing",
                "message": "This upload is still being read.",
            },
        )
    pages = _extract_pdf_pages(blob.content, payload.page_numbers)
    if not pages:
        raise HTTPException(status_code=422, detail="None of those pages exist in the PDF")
    # Same reason as the first parse: re-reading pages is minutes of model
    # work, so the job records that it is running and the client polls.
    job.undo_stack = [*job.undo_stack, job.structure][-20:]
    job.status = "processing"
    job.stage = UploadStage.RECEIVING_FILE.value
    job.error_message = None
    job.failure_reason = None
    job.incident_id = None
    job.completed_at = None
    job.parse_lease_token = None
    job.parse_lease_until = None
    blob.parse_metadata = {
        "title": _title_from_filename(blob.filename),
        "sourceType": LessonSourceType.PDF.value,
        "contentIsExtractedText": False,
        "sourceMetadata": {
            "retryOfUploadId": str(upload_id),
            "retryPageNumbers": sorted(set(payload.page_numbers)),
        },
    }
    await session.commit()
    return {
        "uploadId": str(upload_id),
        "status": job.status,
        "stage": job.stage,
        "pagesRetried": sorted(set(payload.page_numbers)),
        "structure": job.structure,
    }


def _title_of(job: UploadJob, titles: dict[UUID, str | None]) -> str | None:
    """The lesson's title, where this upload has landed one yet."""

    lesson_id = _uuid(job.structure.get("lessonId"))
    return titles.get(lesson_id) if lesson_id is not None else None


@router.get("/uploads/reason-codes", response_model=UploadReasonCatalogueResponse)
async def upload_reason_codes(principal: PrincipalDependency, session: DatabaseSession):
    await require_school_actor(
        session,
        principal,
        roles={UserRole.TEACHER, UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN},
    )
    return {"codes": list(UploadReasonCode), "fallbackCode": "unknown"}


def _upload_reason_code(job: UploadJob) -> UploadReasonCode | None:
    if job.status == "failed":
        return failure_code(job.error_message or job.failure_reason or "")
    if _failed_pages(job.structure):
        return UploadReasonCode.PARTIAL_READING
    return None


@router.get("/uploads", response_model=list[UploadStatusResponse])
async def upload_list(
    principal: PrincipalDependency,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    unsettled_only: Annotated[bool, Query(alias="unsettledOnly")] = False,
) -> list[dict[str, object]]:
    """Every recent upload for this school, in one request.

    A batch of twenty files was twenty polls every few seconds, because the
    batch response comes back before any title exists and the only way to ask
    was one upload at a time. One request answers for the whole screen.

    ``unsettledOnly`` returns just the ones still working, which is what a
    poll actually wants - a batch settles one file at a time and the finished
    ones do not need re-reading.
    """

    actor = await require_school_actor(session, principal)
    query = select(UploadJob).where(UploadJob.school_id == actor.school_id)
    if unsettled_only:
        query = query.where(UploadJob.status.in_(("pending", "processing")))
    jobs = (await session.scalars(query.order_by(UploadJob.created_at.desc()).limit(limit))).all()
    # Titles for the whole page in one query rather than one per upload, which
    # is the thing this route exists to stop.
    lesson_ids = [
        lesson_id
        for lesson_id in (_uuid(job.structure.get("lessonId")) for job in jobs)
        if lesson_id is not None
    ]
    titles: dict[UUID, str | None] = {}
    if lesson_ids:
        rows = await session.execute(
            select(Lesson.id, Lesson.title).where(Lesson.id.in_(lesson_ids))
        )
        titles = {lesson_id: title for lesson_id, title in rows.all()}  # noqa: C416
    return [
        {
            "id": str(job.id),
            "status": job.status,
            "stage": job.stage,
            "lessonTitle": _title_of(job, titles),
            "reviewReady": job.status in {"ready", "confirmed"},
            # Deliberately not the segments: this is the list, and a school
            # with twenty uploads of eleven segments each would be sending a
            # lesson's worth of body text to render a progress bar.
            "segments": [],
            "failedPages": _failed_pages(job.structure),
            "structure": job.structure,
            "error": job.error_message,
            "failureReason": job.failure_reason,
            "reasonCode": _upload_reason_code(job),
            "incidentId": job.incident_id,
        }
        for job in jobs
    ]


@router.get("/uploads/{upload_id}", response_model=UploadStatusResponse)
async def upload_status(
    upload_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    actor = await require_school_actor(session, principal)
    job = await session.get(UploadJob, upload_id)
    if job is None or job.school_id != actor.school_id:
        raise HTTPException(status_code=404, detail="Upload not found")
    lesson_id = _uuid(job.structure.get("lessonId"))
    lesson = await session.get(Lesson, lesson_id) if lesson_id else None
    segments = (
        (
            await session.scalars(
                select(LessonSegment)
                .where(LessonSegment.lesson_id == lesson_id)
                .order_by(LessonSegment.sequence_order)
            )
        ).all()
        if lesson_id
        else []
    )
    from nevo.api.deferred_media import media_summary

    return {
        "id": str(job.id),
        "status": job.status,
        "stage": job.stage,
        "reviewReady": job.status in {"ready", "confirmed"},
        "mediaPreparation": await media_summary(session, lesson_id) if lesson_id else None,
        "lessonTitle": lesson.title if lesson else None,
        "segments": [
            {
                "segmentKey": item.segment_key,
                "title": item.title,
                "contentType": item.content_type.value,
                "sequenceOrder": item.sequence_order,
                "estimatedMinutes": item.estimated_minutes,
                "needsReview": item.needs_review,
            }
            for item in segments
        ],
        "failedPages": _failed_pages(job.structure),
        "structure": job.structure,
        "error": job.error_message,
        "failureReason": job.failure_reason,
        "reasonCode": _upload_reason_code(job),
        "incidentId": job.incident_id,
    }


@router.put("/uploads/{upload_id}/structure", response_model=UploadStructureResponse)
async def update_upload_structure(
    upload_id: UUID,
    payload: UploadStructureWrite,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    actor = await require_school_actor(session, principal)
    job = await session.get(UploadJob, upload_id)
    if job is None or job.school_id != actor.school_id:
        raise HTTPException(status_code=404, detail="Upload not found")
    job.undo_stack = [*job.undo_stack, job.structure][-20:]
    job.structure = payload.structure.model_dump(by_alias=True, mode="json")
    await session.commit()
    return {"id": str(job.id), "structure": job.structure}


@router.post("/uploads/{upload_id}/undo", response_model=UploadStructureResponse)
async def undo_upload_structure(
    upload_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    actor = await require_school_actor(
        session, principal, roles={UserRole.TEACHER, UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}
    )
    job = await session.get(UploadJob, upload_id)
    if job is None or job.school_id != actor.school_id:
        raise HTTPException(status_code=404, detail="Upload not found")
    if not job.undo_stack:
        raise HTTPException(status_code=409, detail="There are no upload changes to undo")
    history = list(job.undo_stack)
    job.structure = history.pop()
    job.undo_stack = history
    await session.commit()
    return {"id": str(job.id), "structure": job.structure, "canUndo": bool(history)}


async def _names_for(session: DatabaseSession, user_ids: set[UUID | None]) -> dict[UUID, str]:
    """Names for a page's worth of people, in one query.

    Returns nothing for an id it cannot resolve rather than a placeholder: a
    name that reaches a child attributed to a teacher has to be that
    teacher's, and "Nevo user" over a note from Mrs Adeyemi is worse than no
    name at all.
    """

    wanted = {user_id for user_id in user_ids if user_id is not None}
    if not wanted:
        return {}
    rows = await session.execute(
        select(User.id, User.first_name, User.last_name).where(User.id.in_(wanted))
    )
    named: dict[UUID, str] = {}
    for user_id, first_name, last_name in rows:
        name = " ".join(part for part in (first_name, last_name) if part).strip()
        if name:
            named[user_id] = name
    return named


async def _offline_package_payload(
    session: DatabaseSession, lesson_id: UUID, actor: User | None = None
) -> dict[str, object]:
    from nevo.intelligence.session_delivery import lesson_delivery_config

    config = (
        await lesson_delivery_config(session, actor, lesson_id)
        if actor and actor.role == UserRole.STUDENT
        else {}
    )
    sitting = (
        await session.scalar(
            select(LessonSession)
            .where(
                LessonSession.student_id == actor.id,
                LessonSession.lesson_id == lesson_id,
                LessonSession.completion_status == LessonCompletionStatus.IN_PROGRESS,
                LessonSession.ended_at.is_(None),
            )
            .order_by(LessonSession.started_at.desc())
            .limit(1)
        )
        if actor
        else None
    )
    recommendations = (sitting.delivery_state or {}).get("recommendations", {}) if sitting else {}
    lesson = await session.get(Lesson, lesson_id)
    modules = list(
        await session.scalars(
            select(LessonModule)
            .where(LessonModule.lesson_id == lesson_id)
            .order_by(LessonModule.sequence_order)
        )
    )
    segments = (
        await session.scalars(
            select(LessonSegment)
            .where(LessonSegment.lesson_id == lesson_id)
            .order_by(LessonSegment.sequence_order)
        )
    ).all()
    if lesson is None:
        raise HTTPException(status_code=404, detail="Lesson not found")
    from nevo.api.lesson_review import approved_check_ids

    reviewed_checks = await approved_check_ids(session, lesson_id)
    modules = delivery_modules(lesson.id, segments, modules)
    # Built as a dict and then validated through OfflinePackage, so the shape
    # the spec publishes is the shape that actually ships. Ask B60.
    payload: dict[str, object] = {
        "id": str(lesson.id),
        "title": lesson.title,
        "version": str(lesson.parser_version),
        "modules": [
            {
                "id": str(module.id),
                "title": module.title,
                "sequenceOrder": module.sequence_order,
                "segmentIds": module.segment_ids,
                "segmentRecordIds": [
                    str(segment.id)
                    for key in module.segment_ids
                    for segment in segments
                    if key in {segment.segment_key, str(segment.id)}
                ],
                "recap": module.recap,
                "preview": module.preview,
            }
            for module in modules
        ],
        "recap": lesson.recap,
        "assessment": checkpoint_payloads(
            lesson.assessment or [],
            segment_key="lesson-assessment",
            presentation_seed=str(actor.id),
        ),
        "segments": [
            {
                "id": str(item.id),
                "key": item.segment_key,
                "title": item.title,
                "body": item.body,
                "contentType": item.content_type.value,
                "readingChunks": item.reading_chunks or reading_chunks(item.segment_key, item.body),
                "readingGroups": reading_groups(
                    item.reading_chunks or reading_chunks(item.segment_key, item.body), config
                ),
                "sequenceOrder": item.sequence_order,
                "availableModalities": student_modalities(item),
                "availableFormats": student_modalities(item),
                "recommendedFormat": recommendations.get(str(item.id))
                if recommendations.get(str(item.id)) in student_modalities(item)
                else None,
                "primaryModality": segment_choice(sitting, item).get("modality"),
                "deliveryPreference": segment_choice(sitting, item) or None,
                "modalityVariants": {
                    "text": item.text_variant,
                    "visual": (
                        safety_reviewed_visual(item.visual_variant)
                        if "visual" in student_modalities(item)
                        else None
                    ),
                    "audio": item.audio_variant,
                    "interactive": student_activity(item),
                    "calculation": calculation_for_delivery(item.calculation_variant),
                },
                # Offline too: the point of the offline package is a lesson
                # that still adapts where there is no network, and an
                # adaptation that cannot reach its text is not one.
                "depthVariants": depth_payloads(
                    item.depth_variants, item.text_variant, for_student=True
                ),
                "comprehensionCheckpoints": checkpoint_payloads(
                    item.comprehension_checkpoints,
                    segment_key=item.segment_key,
                    presentation_seed=str(actor.id),
                    question_offset=item.sequence_order - 1,
                    reviewed_question_ids={qid for sid, qid in reviewed_checks if sid == str(item.id)},
                ),
            }
            for item in segments
        ],
    }
    return OfflinePackage.model_validate(payload).model_dump(by_alias=True, mode="json")


def _upload_structure(parsed) -> dict[str, object]:
    """Shape a parse result for the structure review screen.

    ``lessons`` is the real structure: a unit or term upload can become
    several lessons. ``lessonId`` and ``modules`` mirror the first lesson so
    single-lesson clients written against the old shape keep working.
    """
    modules = [
        {
            "title": module.title,
            "sequenceOrder": position,
            "segmentIds": list(module.segment_keys),
            "recap": module.recap,
            "preview": module.preview,
        }
        for position, module in enumerate(getattr(parsed, "modules", ()), start=1)
    ]
    lessons = [
        {
            "lessonId": str(parsed.lesson_id),
            "title": parsed.title,
            "sequenceOrder": 1,
            "modules": modules,
            "segmentIds": [segment.segment_key for segment in parsed.segments]
            if not modules
            else [],
        }
    ]
    segment_rows = [
        {
            "segmentKey": str(item.segment_key),
            "title": item.title,
            "contentType": item.content_type.value,
            "sequenceOrder": item.sequence_order,
            "estimatedMinutes": item.estimated_minutes,
            "needsReview": item.needs_review,
        }
        for item in parsed.segments
    ]
    return {
        "title": parsed.title,
        "segments": segment_rows,
        "lessons": lessons,
        "lessonId": str(parsed.lesson_id),
        "modules": modules,
        "reviewNotes": list(parsed.review_notes),
    }


def _failed_pages(structure: dict[str, object]) -> list[int]:
    direct = structure.get("failedPages")
    if isinstance(direct, list):
        return sorted({int(item) for item in direct if isinstance(item, int) and item > 0})
    notes = structure.get("reviewNotes")
    if not isinstance(notes, list):
        return []
    pages: set[int] = set()
    for note in notes:
        if not isinstance(note, dict) or note.get("code") not in {
            "page_text_missing",
            "page_extraction_failed",
        }:
            continue
        values = note.get("pageNumbers")
        if isinstance(values, list):
            pages.update(item for item in values if isinstance(item, int) and item > 0)
    return sorted(pages)


def _extract_pdf_pages(content: bytes, page_numbers: list[int]) -> list[SourcePage]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(BytesIO(content))
    except Exception as error:
        raise HTTPException(status_code=400, detail="Could not read PDF pages") from error
    pages: list[SourcePage] = []
    for page_number in sorted(set(page_numbers)):
        if page_number < 1 or page_number > len(reader.pages):
            continue
        text = reader.pages[page_number - 1].extract_text() or ""
        pages.append(SourcePage(page_number=page_number, text=text))
    return pages


@router.post("/uploads/{upload_id}/confirm", response_model=UploadConfirmedResponse)
async def confirm_upload(
    upload_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    """Turn a reviewed upload into lessons.

    A unit or term upload parses into one lesson; the teacher splits it in the
    review screen by editing ``structure.lessons``. Confirm honours that: the
    first entry keeps the original lesson, and each additional entry becomes a
    new lesson with the segments the teacher assigned to it moved across.
    """
    actor = await require_school_actor(session, principal)
    job = await session.get(UploadJob, upload_id)
    if job is None or job.school_id != actor.school_id:
        raise HTTPException(status_code=404, detail="Upload not found")
    root_lesson_id = job.structure.get("lessonId")
    if not root_lesson_id:
        raise HTTPException(status_code=409, detail="Upload has no parsed lesson")
    root_id = UUID(str(root_lesson_id))
    root_lesson = await session.get(Lesson, root_id)
    if root_lesson is None:
        raise HTTPException(status_code=409, detail="Upload has no parsed lesson")

    entries = _structure_lessons(job.structure)
    segments = {
        item.segment_key: item
        for item in (
            await session.scalars(select(LessonSegment).where(LessonSegment.lesson_id == root_id))
        ).all()
    }
    edited_segments = job.structure.get("segments")
    if isinstance(edited_segments, list):
        for edited in edited_segments:
            if not isinstance(edited, dict):
                continue
            segment = segments.get(str(edited.get("segmentKey") or ""))
            title = edited.get("title")
            if segment is not None and isinstance(title, str) and title.strip():
                segment.title = title.strip()
    await session.execute(delete(LessonModule).where(LessonModule.lesson_id == root_id))

    lesson_ids: list[UUID] = []
    pending_module_segments: list[tuple[LessonModule, list[str]]] = []
    for index, entry in enumerate(entries):
        modules = [item for item in entry.get("modules", []) if isinstance(item, dict)]
        entry_id = _uuid(entry.get("lessonId"))
        if entry_id == root_id or (index == 0 and entry_id is None):
            lesson = root_lesson
        else:
            # No id, or an id we do not own: this entry is a new lesson and the
            # server mints it. Position in lessonIds is how the caller matches
            # it back.
            lesson = Lesson(
                school_id=root_lesson.school_id,
                title=str(entry.get("title") or f"{root_lesson.title} ({index + 1})"),
                source_type=root_lesson.source_type,
                status=root_lesson.status,
                subject=root_lesson.subject,
                created_by_user_id=root_lesson.created_by_user_id,
            )
            session.add(lesson)
            await session.flush()
        edited_title = entry.get("title")
        if not edited_title and index == 0:
            edited_title = job.structure.get("title")
        if isinstance(edited_title, str) and edited_title.strip():
            lesson.title = edited_title.strip()
        lesson_ids.append(lesson.id)

        claimed = [
            segments[key]
            for key in (
                [key for module in modules for key in module.get("segmentIds", [])]
                if modules
                else entry.get("segmentIds") or (list(segments) if len(entries) == 1 else [])
            )
            if isinstance(key, str) and key in segments
        ]
        for position, segment in enumerate(claimed, start=1):
            segment.lesson_id = lesson.id
            segment.sequence_order = position
        # Counts are denormalised onto the lesson, so they have to follow the
        # segments to whichever lesson they were moved into.
        lesson.segment_count = len(claimed)
        lesson.review_segment_count = sum(1 for item in claimed if item.needs_review)
        lesson.estimated_minutes = sum(item.estimated_minutes for item in claimed)

        for module in modules:
            module_row = LessonModule(
                id=uuid4(),
                lesson_id=lesson.id,
                title=str(module.get("title") or "Module"),
                recap=module.get("recap"),
                preview=module.get("preview"),
                sequence_order=int(module.get("sequenceOrder") or 1),
                segment_ids=(
                    list(segment_ids)
                    if isinstance((segment_ids := module.get("segmentIds")), list)
                    else []
                ),
            )
            session.add(module_row)
            pending_module_segments.append((module_row, module_row.segment_ids))

    # These rows are referenced by lesson_segments.module_id. Flush their
    # inserts before assigning those foreign keys; without this boundary,
    # SQLAlchemy may batch segment updates ahead of the module inserts.
    await session.flush()
    for module_row, segment_keys in pending_module_segments:
        for key in segment_keys:
            if key in segments:
                segments[key].module_id = module_row.id

    job.status = "confirmed"
    job.stage = UploadStage.READY_TO_ASSIGN.value
    await session.commit()
    return {
        "lessonId": str(lesson_ids[0]),
        "lessonIds": [str(item) for item in lesson_ids],
        "status": job.status,
    }


def _structure_lessons(structure: dict[str, object]) -> list[dict[str, object]]:
    """The lessons a confirmed upload should produce.

    Falls back to the single-lesson shape when a client has not sent
    ``lessons``, so an older console keeps working unchanged.
    """
    entries = structure.get("lessons")
    if isinstance(entries, list) and entries:
        lessons = [item for item in entries if isinstance(item, dict)]
        if lessons:
            return lessons
    modules = structure.get("modules")
    return [
        {
            "lessonId": structure.get("lessonId"),
            "modules": modules if isinstance(modules, list) else [],
        }
    ]


def _uuid(value: object) -> UUID | None:
    """Parse an identifier that may be absent or malformed, without raising."""
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None
