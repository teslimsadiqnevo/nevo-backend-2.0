import hashlib
import json
import logging
import secrets
from datetime import UTC, datetime, time, timedelta
from io import BytesIO
from typing import Annotated, Literal, cast
from uuid import UUID, uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import (
    APIRouter,
    Depends,
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
from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.access import accessible_lessons
from nevo.api.auth import OptionalPrincipalDependency, PrincipalDependency
from nevo.api.consent import StudentLearningConsent
from nevo.api.content import get_content_parsing_service
from nevo.api.dependencies import DatabaseSession, SessionFactory
from nevo.api.frontend_unblockers import (
    MAX_LESSON_UPLOAD_BYTES,
    _extract_text,
    _source_type,
    _title_from_filename,
)
from nevo.api.learning_support import require_learning_support_if_admin
from nevo.api.lesson_contracts import checkpoint_payloads, reading_chunks
from nevo.api.product_common import (
    actor_user,
    require_approved_lessons,
    require_class_access,
    require_school_actor,
    require_student_access,
)
from nevo.api.response_models import (
    AssignmentCreatedResponse,
    AssignmentResponse,
    AssignmentUpdatedResponse,
    BatchUploadResponse,
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
    UploadRetryResponse,
    UploadStatusResponse,
    UploadStructureDocument,
    UploadStructureResponse,
)
from nevo.content_parsing.entities import ContentParseRequest, SourcePage
from nevo.content_parsing.failures import failure_reason, new_incident
from nevo.content_parsing.service import ContentParsingService
from nevo.db.models.account import Class, School, StudentClassEnrollment, User
from nevo.db.models.attention_flag import AttentionFlag
from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.models.frontend_support import Concept, LessonAssignment
from nevo.db.models.learner_profile import LearnerProfile
from nevo.db.models.mastery import StudentConceptScheduling
from nevo.db.models.product import (
    LessonModule,
    LessonProgress,
    LessonQuestionAttempt,
    OfflineDownload,
    StudentOnboardingGrant,
    UploadJob,
    UploadSourceBlob,
)
from nevo.db.models.signal_event import LessonSession
from nevo.domain.accounts.age_bands import coerce_band
from nevo.domain.accounts.vocabulary import SsoProvider, UserRole
from nevo.domain.intelligence.vocabulary import (
    AssignmentStatus,
    LessonScope,
    LessonSourceType,
    UploadStage,
)
from nevo.domain.signal_events.vocabulary import LessonCompletionStatus
from nevo.learner_profiles.post_lesson_worker import PostLessonProcessingWorker
from nevo.ops.background import spawn
from nevo.sso.service import SsoService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["learning product"])
CONSENT_WITHDRAWN_RESPONSE = {
    403: {
        "description": (
            "consent_withdrawn: the learner's consent was withdrawn and this "
            "processing operation is suspended"
        )
    }
}
ParsingService = Annotated[ContentParsingService, Depends(get_content_parsing_service)]
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
    #: Where the learner is, as a zero-based index. The first module is 0 and
    #: the first segment in it is 0.
    #:
    #: Deliberately not the same counting as a segment's ``sequenceOrder``,
    #: which is one-based and is the segment's own number in the lesson. These
    #: are a cursor; that is an ordinal. Both were correct and neither said so,
    #: which is why a client had to guess.
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
    source: Literal["checkpoint", "assessment"] = "checkpoint"
    answer: JsonValue
    client_attempt_id: UUID | None = Field(default=None, alias="clientAttemptId")


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


class CloudImportRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_type: Literal["google_drive", "onedrive"] = Field(alias="sourceType")
    file_id: str = Field(alias="fileId", min_length=1, max_length=500)
    drive_id: str | None = Field(default=None, alias="driveId", max_length=500)
    title: str | None = Field(default=None, max_length=255)
    scope: str = Field(default="lesson", pattern="^(lesson|unit|term)$")
    subject: str | None = Field(default=None, max_length=120)


class RetryPagesRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    page_numbers: list[int] = Field(alias="pageNumbers", min_length=1, max_length=100)


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
    prompts = await _socratic_handoff(session, item)
    payload["handoffTo"] = "socratic_panel" if prompts else None
    payload["guidedPrompts"] = prompts
    payload["advanceAfterHandoff"] = bool(prompts)
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
) -> list[dict[str, str]]:
    """Return the server-owned SCRUM-241 hand-off after three misses."""

    recent = list(
        await session.scalars(
            select(LessonQuestionAttempt)
            .where(
                LessonQuestionAttempt.session_id == item.session_id,
                LessonQuestionAttempt.question_id == item.question_id,
            )
            .order_by(LessonQuestionAttempt.attempt_number.desc())
            .limit(3)
        )
    )
    if len(recent) < 3 or any(attempt.correct is not False for attempt in recent):
        return []
    concept = str(item.question_snapshot.get("conceptName") or "this idea").strip()
    return [
        {"id": f"{item.question_id}-notice", "prompt": "What is the question asking you to find?"},
        {
            "id": f"{item.question_id}-connect",
            "prompt": f"What do you already know about {concept} that could help here?",
        },
        {"id": f"{item.question_id}-try", "prompt": "What is one small step you could try first?"},
    ]


async def _question_for_attempt(
    session: DatabaseSession,
    lesson: Lesson,
    payload: LessonQuestionAttemptWrite,
) -> tuple[dict[str, object], UUID | None]:
    if payload.source == "assessment":
        questions = checkpoint_payloads(lesson.assessment or [], segment_key="lesson-assessment")
        segment_id = None
    else:
        if payload.segment_id is None:
            raise HTTPException(status_code=422, detail="segmentId is required for a checkpoint")
        segment = await session.get(LessonSegment, payload.segment_id)
        if segment is None or segment.lesson_id != lesson.id:
            raise HTTPException(status_code=404, detail="Lesson question not found")
        questions = checkpoint_payloads(
            segment.comprehension_checkpoints,
            segment_key=segment.segment_key,
        )
        segment_id = segment.id
    question = next(
        (item for item in questions if str(item.get("id")) == payload.question_id),
        None,
    )
    if question is None:
        raise HTTPException(status_code=404, detail="Lesson question not found")
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
    return [
        _lesson_summary(
            item,
            assignment_count=int(counts.get(item.id, 0)),
            author_names=authors,
            unapproved_segment_count=outstanding.get(item.id, 0),
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


@router.get("/lessons/{lesson_id}", response_model=LessonDetailResponse)
async def lesson_detail(
    lesson_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    actor, lesson = await _lesson_for_actor(lesson_id, principal, session)
    # A child's device has no use for a teacher's review state, and sending it
    # anywhere it is not needed is how it ends up rendered somewhere it should
    # not be. One route serves both, so it is omitted rather than removed.
    for_teacher = actor.role is not UserRole.STUDENT
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
    return {
        **_lesson_summary(
            lesson,
            assignment_count=int(assignment_count or 0),
            unapproved_segment_count=(await _unapproved_counts(session, [lesson.id])).get(
                lesson.id, 0
            ),
        ),
        "classes": await _classes_for_lesson(session, lesson.id),
        "confirmationSummary": lesson.confirmation_summary,
        "recap": lesson.recap,
        "assessment": list(lesson.assessment or []),
        "segments": [
            {
                "id": str(item.id),
                "segmentKey": item.segment_key,
                "sequenceOrder": item.sequence_order,
                "contentType": item.content_type.value,
                "title": item.title,
                "body": item.body,
                "readingChunks": reading_chunks(item.segment_key, item.body),
                "availableModalities": item.available_modalities,
                "comprehensionCheckpoints": checkpoint_payloads(
                    item.comprehension_checkpoints, segment_key=item.segment_key
                ),
                "textVariant": item.text_variant,
                "visualVariant": item.visual_variant,
                "audioVariant": item.audio_variant,
                "interactiveVariant": item.interactive_variant,
                "calculationVariant": item.calculation_variant,
                "depthVariants": item.depth_variants,
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
            }
            for item in modules
        ],
    }


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
    responses=CONSENT_WITHDRAWN_RESPONSE,
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
    progress = await session.scalar(
        select(LessonProgress).where(
            LessonProgress.student_id == actor.id,
            LessonProgress.lesson_id == lesson_id,
        )
    )
    existing = await session.scalar(
        select(LessonSession)
        .where(
            LessonSession.student_id == actor.id,
            LessonSession.lesson_id == lesson_id,
            LessonSession.completion_status == LessonCompletionStatus.IN_PROGRESS,
        )
        .order_by(LessonSession.started_at.desc())
    )
    if existing:
        return {
            "sessionId": str(existing.id),
            "resumed": True,
            "depth": existing.delivery_depth,
            "reroutedFromSessionId": existing.rerouted_from_session_id,
            "checkPosition": progress.check_position if progress else None,
            "checkResumableUntil": progress.check_resumable_until if progress else None,
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
            return {
                "sessionId": str(check_session.id),
                "resumed": True,
                "depth": check_session.delivery_depth,
                "reroutedFromSessionId": check_session.rerouted_from_session_id,
                "checkPosition": progress.check_position,
                "checkResumableUntil": progress.check_resumable_until,
            }
    record = LessonSession(
        id=uuid4(),
        student_id=actor.id,
        lesson_id=lesson_id,
        started_at=datetime.now(UTC),
        completion_status=LessonCompletionStatus.IN_PROGRESS,
    )
    session.add(record)
    await session.commit()
    return {
        "sessionId": str(record.id),
        "resumed": False,
        "depth": record.delivery_depth,
        "reroutedFromSessionId": record.rerouted_from_session_id,
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
    lesson_session = await session.get(LessonSession, payload.session_id)
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
            return await _attempt_payload_with_outcome(session, existing)
    question, segment_id = await _question_for_attempt(session, lesson, payload)
    attempt_number = int(
        await session.scalar(
            select(func.coalesce(func.max(LessonQuestionAttempt.attempt_number), 0) + 1).where(
                LessonQuestionAttempt.session_id == payload.session_id,
                LessonQuestionAttempt.question_id == payload.question_id,
            )
        )
        or 1
    )
    # The snapshot is an untyped bag, so what comes out of it is object. Cast
    # rather than widen _normalise_answer's signature: it is the one place that
    # knows what shapes an answer can be, and loosening it there would let
    # anything through everywhere else.
    answer_key = cast(JsonValue | None, question.get("answerKey"))
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
        correct=(
            None
            if answer_key is None
            else _normalise_answer(payload.answer) == _normalise_answer(answer_key)
        ),
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return await _attempt_payload_with_outcome(session, record)


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
    lesson_session = await session.get(LessonSession, payload.session_id)
    if lesson_session is None or lesson_session.student_id != actor.id:
        raise HTTPException(status_code=404, detail="Lesson session not found")
    progress = await session.scalar(
        select(LessonProgress).where(
            LessonProgress.student_id == actor.id,
            LessonProgress.lesson_id == lesson_id,
        )
    )
    if progress is None:
        progress = LessonProgress(student_id=actor.id, lesson_id=lesson_id)
        session.add(progress)
    progress.session_id = payload.session_id
    progress.assignment_id = payload.assignment_id
    progress.module_position = payload.module_position
    progress.segment_position = payload.segment_position
    if "check_position" in payload.model_fields_set:
        progress.check_position = payload.check_position
        progress.check_resumable_until = (
            _end_of_day() if payload.check_position is not None else None
        )
    progress.status = payload.status
    progress.started_at = progress.started_at or lesson_session.started_at
    lesson_session.exit_position = str(payload.segment_position)
    derived_result = await _derive_result_state(session, lesson_session.id)
    # A lesson that was never attempted is not the "nothing landed" result.
    # Keep its sitting open at the saved cursor so the next launch resumes it.
    not_attempted = (
        payload.status is LessonCompletionStatus.COMPLETED
        and derived_result == "not_attempted"
    )
    if not_attempted:
        progress.status = LessonCompletionStatus.IN_PROGRESS
    elif payload.status in {"completed", "exited"}:
        lesson_session.ended_at = datetime.now(UTC)
        lesson_session.completion_status = LessonCompletionStatus(payload.status)
    reroute: dict[str, object] | None = None
    nothing_landed = (
        payload.status is LessonCompletionStatus.COMPLETED
        and derived_result == "nothing_landed"
    )
    if payload.status == "completed" and not not_attempted:
        progress.completed_at = datetime.now(UTC)
        assignment = (
            await session.get(LessonAssignment, payload.assignment_id)
            if payload.assignment_id
            else None
        )
        if assignment and assignment.student_id == actor.id and not nothing_landed:
            assignment.status = "completed"
            assignment.completed_at = datetime.now(UTC)
    if nothing_landed:
        lower_session = LessonSession(
            id=uuid4(),
            student_id=actor.id,
            lesson_id=lesson_id,
            started_at=datetime.now(UTC),
            completion_status=LessonCompletionStatus.IN_PROGRESS,
            delivery_depth="lower",
            rerouted_from_session_id=lesson_session.id,
        )
        session.add(lower_session)
        progress.session_id = lower_session.id
        progress.status = LessonCompletionStatus.IN_PROGRESS
        progress.module_position = 0
        progress.segment_position = 0
        progress.completed_at = None
        reroute = {
            "sessionId": str(lower_session.id),
            "lessonId": str(lesson_id),
            "depth": "lower",
            "segmentPosition": 0,
            "reason": "nothing_landed",
        }
    elif not_attempted:
        reroute = {
            "sessionId": str(lesson_session.id),
            "lessonId": str(lesson_id),
            "depth": lesson_session.delivery_depth,
            "segmentPosition": progress.segment_position,
            "reason": "not_attempted",
        }
    await session.commit()

    intelligence: dict[str, object] = {"status": "not_run"}
    if payload.status == "completed" and not not_attempted:
        worker = getattr(request.app.state, "post_lesson_worker", None)
        if isinstance(worker, PostLessonProcessingWorker):
            intelligence["status"] = await worker.enqueue(
                session_id=lesson_session.id,
                student_id=actor.id,
                completed_at=lesson_session.ended_at,
            )
        else:
            intelligence["status"] = "deferred"
    mastered, revisit = await _check_in_outcome(session, lesson_session.id)
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
        return f"You had every question right on {_join(kept)}."
    if again and not kept:
        return f"{_join(again).capitalize()} is worth another look."
    return f"You had {_join(kept)} right. {_join(again).capitalize()} is worth another look."


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
    return {
        "student": {"id": str(actor.id), "firstName": actor.first_name},
        "assignments": due,
        "recentProgress": [
            {
                "lessonId": str(item.lesson_id),
                "status": item.status,
                "segmentPosition": item.segment_position,
                "updatedAt": item.updated_at,
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
        )
    )
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
    }


@router.get("/teachers/me/dashboard", response_model=TeacherDashboardResponse)
async def teacher_dashboard(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    actor = await require_school_actor(
        session, principal, roles={UserRole.TEACHER, UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}
    )
    class_query = select(Class).where(Class.school_id == actor.school_id)
    if actor.role == UserRole.TEACHER:
        from nevo.db.models.teacher_assignment import TeacherClassAssignment

        class_query = class_query.join(TeacherClassAssignment).where(
            TeacherClassAssignment.teacher_id == actor.id,
            TeacherClassAssignment.removed_at.is_(None),
        )
    classes = (await session.scalars(class_query.order_by(Class.name))).all()
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
    package = await _offline_package_payload(session, lesson_id)
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
    await _lesson_for_actor(lesson_id, principal, session)
    return await _offline_package_payload(session, lesson_id)


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
    package = await _offline_package_payload(session, lesson_id)
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
        200: {
            "description": (
                "A zip holding lesson.json (the lesson package) and "
                "manifest.json. Media is referenced by URL, not bundled."
            ),
            "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def offline_package(
    lesson_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> Response:
    actor, lesson = await _lesson_for_actor(lesson_id, principal, session)
    if actor.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Student account required")
    payload = await _offline_package_payload(session, lesson_id)
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
    parser: ParsingService,
    sessions: SessionFactory,
) -> dict[str, object]:
    actor = await require_school_actor(
        session, principal, roles={UserRole.TEACHER, UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}
    )
    job = UploadJob(
        school_id=actor.school_id,
        requested_by_id=actor.id,
        scope=payload.scope,
        filename=payload.filename,
        status="processing",
        stage="lessons",
    )
    session.add(job)
    await session.commit()
    # The job row and GET /uploads/{id} already existed to report progress,
    # but the parse ran inside this request anyway, so the caller waited for
    # minutes of model calls and media generation before being told to poll.
    _parse_into_job(
        job_id=job.id,
        request=ContentParseRequest(
            title=payload.title,
            source_type=payload.source_type,
            source_text=payload.source_text,
            source_metadata={"subject": payload.subject} if payload.subject else {},
        ),
        actor_id=actor.id,
        parser=parser,
        sessions=sessions,
    )
    return {"uploadId": str(job.id), "status": job.status, "stage": job.stage}


@router.post("/uploads", response_model=UploadCreatedResponse, status_code=status.HTTP_201_CREATED)
async def staged_file_upload(
    principal: PrincipalDependency,
    session: DatabaseSession,
    parser: ParsingService,
    # The parse outlives the request, so it needs a factory to open its own
    # session from. Declared here because FastAPI only resolves dependencies
    # on a route handler; _ingest_one_file is a plain function and cannot ask
    # for one itself.
    sessions: SessionFactory,
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
        parser=parser,
        sessions=sessions,
    )


def _parse_into_job(
    *,
    job_id: UUID,
    request: ContentParseRequest,
    actor_id: UUID,
    parser: ContentParsingService,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Parse behind the response, then write the outcome onto the job."""

    async def note_stage(stage: UploadStage) -> None:
        """Move the job on so the processing screen can say where it is."""

        async with sessions.begin() as session:
            job = await session.get(UploadJob, job_id)
            if job is not None:
                job.stage = stage.value

    async def work() -> None:
        try:
            parsed = await parser.parse(
                request=request,
                requested_by_user_id=actor_id,
                on_stage=note_stage,
            )
        except Exception as error:
            # The same 12 hex characters an unhandled 500 carries, so a teacher
            # looking at a failed parse has something to quote and we can find
            # it in the log. A parse fails behind the response, so there is no
            # 500 for it to ride on and it has to be written onto the job.
            incident = new_incident()
            logger.exception("Upload parse %s failed, incident %s", job_id, incident)
            async with sessions.begin() as session:
                job = await session.get(UploadJob, job_id)
                if job is not None:
                    job.status = "failed"
                    # Raw, and staying raw: this is for us. It is whatever the
                    # driver or the provider said, and it was never prose.
                    job.error_message = str(error)[:1000]
                    job.incident_id = incident
                    job.failure_reason = failure_reason(error)
            raise
        async with sessions.begin() as session:
            job = await session.get(UploadJob, job_id)
            if job is None:
                return
            job.status = "ready"
            job.stage = "structure"
            job.structure = _upload_structure(parsed)
            job.completed_at = datetime.now(UTC)

    spawn(work, name=f"upload-parse-{job_id}")


async def _ingest_one_file(
    *,
    file: UploadFile,
    filename: str,
    scope: str,
    subject: str | None,
    principal: PrincipalDependency,
    session: DatabaseSession,
    parser: ParsingService,
    sessions: SessionFactory,
) -> dict[str, object]:
    """Parse one uploaded file into a staged upload job.

    Shared by the single-file and batch routes so both apply the same size
    limit, text extraction and source retention.
    """
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Lesson file exceeds 50 MB")
    source_text = _extract_text(filename, content)
    if not source_text.strip():
        raise HTTPException(status_code=400, detail="No readable lesson text was found")
    result = await staged_upload(
        UploadRequest(
            title=_title_from_filename(filename),
            filename=filename,
            scope=scope,
            sourceType=_source_type(filename),
            sourceText=source_text,
            subject=subject,
        ),
        principal,
        session,
        parser,
        sessions,
    )
    session.add(
        UploadSourceBlob(
            upload_id=UUID(str(result["uploadId"])),
            filename=filename,
            content_type=file.content_type or "application/octet-stream",
            content=content,
        )
    )
    await session.commit()
    return result


@router.post(
    "/uploads/batch",
    response_model=BatchUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def staged_batch_upload(
    principal: PrincipalDependency,
    session: DatabaseSession,
    parser: ParsingService,
    sessions: SessionFactory,
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
                parser=parser,
                sessions=sessions,
            )
        except HTTPException as error:
            results.append(
                {
                    "filename": filename,
                    "accepted": False,
                    "error": str(error.detail),
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
    parser: ParsingService,
    sessions: SessionFactory,
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
    result = await staged_upload(
        UploadRequest(
            title=payload.title or _title_from_filename(cloud_file.filename),
            filename=cloud_file.filename,
            scope=payload.scope,
            sourceType=LessonSourceType(payload.source_type),
            sourceText=source_text,
            subject=payload.subject,
        ),
        principal,
        session,
        parser,
        sessions,
    )
    session.add(
        UploadSourceBlob(
            upload_id=UUID(str(result["uploadId"])),
            filename=cloud_file.filename,
            content_type=cloud_file.content_type,
            content=cloud_file.content,
        )
    )
    await session.commit()
    return result


@router.post(
    "/uploads/{upload_id}/retry-pages",
    response_model=UploadRetryResponse,
)
async def retry_upload_pages(
    upload_id: UUID,
    payload: RetryPagesRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
    parser: ParsingService,
    sessions: SessionFactory,
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
    pages = _extract_pdf_pages(blob.content, payload.page_numbers)
    if not pages:
        raise HTTPException(status_code=422, detail="None of those pages exist in the PDF")
    # Same reason as the first parse: re-reading pages is minutes of model
    # work, so the job records that it is running and the client polls.
    job.undo_stack = [*job.undo_stack, job.structure][-20:]
    job.status = "processing"
    job.stage = "lessons"
    job.error_message = None
    await session.commit()
    _parse_into_job(
        job_id=upload_id,
        request=ContentParseRequest(
            title=_title_from_filename(blob.filename),
            source_type=LessonSourceType.PDF,
            pages=tuple(pages),
            source_metadata={"retryOfUploadId": str(upload_id)},
        ),
        actor_id=actor.id,
        parser=parser,
        sessions=sessions,
    )
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
            # Deliberately not the segments: this is the list, and a school
            # with twenty uploads of eleven segments each would be sending a
            # lesson's worth of body text to render a progress bar.
            "segments": [],
            "failedPages": _failed_pages(job.structure),
            "structure": job.structure,
            "error": job.error_message,
            "failureReason": job.failure_reason,
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
    return {
        "id": str(job.id),
        "status": job.status,
        "stage": job.stage,
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


async def _offline_package_payload(session: DatabaseSession, lesson_id: UUID) -> dict[str, object]:
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
    # Built as a dict and then validated through OfflinePackage, so the shape
    # the spec publishes is the shape that actually ships. Ask B60.
    payload: dict[str, object] = {
        "id": str(lesson.id),
        "title": lesson.title,
        "version": lesson.parser_version,
        "modules": [
            {
                "id": str(module.id),
                "title": module.title,
                "sequenceOrder": module.sequence_order,
                "segmentIds": module.segment_ids,
                "recap": module.recap,
                "preview": module.preview,
            }
            for module in modules
        ],
        "recap": lesson.recap,
        "assessment": checkpoint_payloads(lesson.assessment or [], segment_key="lesson-assessment"),
        "segments": [
            {
                "id": str(item.id),
                "key": item.segment_key,
                "title": item.title,
                "body": item.body,
                "contentType": item.content_type.value,
                "sequenceOrder": item.sequence_order,
                "availableModalities": item.available_modalities,
                "modalityVariants": {
                    "text": item.text_variant,
                    "visual": item.visual_variant,
                    "audio": item.audio_variant,
                    "interactive": item.interactive_variant,
                    "calculation": item.calculation_variant,
                },
                # Offline too: the point of the offline package is a lesson
                # that still adapts where there is no network, and an
                # adaptation that cannot reach its text is not one.
                "depthVariants": item.depth_variants,
                "comprehensionCheckpoints": checkpoint_payloads(
                    item.comprehension_checkpoints, segment_key=item.segment_key
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
    segment_ids = [str(item.segment_key) for item in parsed.segments]
    modules = [
        {
            "title": f"Module {index // 5 + 1}",
            "sequenceOrder": index // 5 + 1,
            "segmentIds": segment_ids[index : index + 5],
            "recap": None,
            "preview": None,
        }
        for index in range(0, len(segment_ids), 5)
    ]
    lessons = [
        {
            "lessonId": str(parsed.lesson_id),
            "title": parsed.title,
            "sequenceOrder": 1,
            "modules": modules,
        }
    ]
    return {
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
        if not isinstance(note, dict) or note.get("code") != "ai_parse_fallback":
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
    await session.execute(delete(LessonModule).where(LessonModule.lesson_id == root_id))

    lesson_ids: list[UUID] = []
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
        lesson_ids.append(lesson.id)

        claimed = [
            segments[key]
            for module in modules
            for key in module.get("segmentIds", [])
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
            session.add(
                LessonModule(
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
            )

    job.status = "confirmed"
    job.stage = "complete"
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
