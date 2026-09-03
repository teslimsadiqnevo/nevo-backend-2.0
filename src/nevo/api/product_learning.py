import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Annotated, Literal
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
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert

from nevo.api.auth import OptionalPrincipalDependency, PrincipalDependency
from nevo.api.content import get_content_parsing_service
from nevo.api.dependencies import DatabaseSession
from nevo.api.frontend_unblockers import _extract_text, _source_type, _title_from_filename
from nevo.api.lesson_contracts import checkpoint_payloads
from nevo.api.product_common import (
    actor_user,
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
    LessonSessionResponse,
    LessonSummaryResponse,
    OfflineDownloadResponse,
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
from nevo.content_parsing.service import ContentParsingService
from nevo.db.models.account import Class, School, StudentClassEnrollment, User
from nevo.db.models.attention_flag import AttentionFlag
from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.models.frontend_support import LessonAssignment
from nevo.db.models.learner_profile import LearnerProfile
from nevo.db.models.product import (
    LessonModule,
    LessonProgress,
    OfflineDownload,
    StudentOnboardingGrant,
    UploadJob,
    UploadSourceBlob,
)
from nevo.db.models.signal_event import LessonSession
from nevo.domain.accounts.vocabulary import SsoProvider, UserRole
from nevo.domain.intelligence.vocabulary import AssignmentStatus, LessonSourceType
from nevo.domain.signal_events.vocabulary import LessonCompletionStatus
from nevo.learner_profiles.post_lesson_worker import PostLessonProcessingWorker
from nevo.sso.service import SsoService

router = APIRouter(prefix="/api/v1", tags=["learning product"])
ParsingService = Annotated[ContentParsingService, Depends(get_content_parsing_service)]
LessonUpload = Annotated[UploadFile, File()]
BatchLessonUpload = Annotated[list[UploadFile], File()]
UploadScope = Annotated[str, Form(pattern="^(lesson|unit|term)$")]
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_BATCH_UPLOAD_FILES = 20
UploadSubject = Annotated[str | None, Form(max_length=120)]
StudentFilter = Annotated[UUID | None, Query(alias="studentId")]
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


class ProgressWrite(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_id: UUID = Field(alias="sessionId")
    assignment_id: UUID | None = Field(default=None, alias="assignmentId")
    module_position: int = Field(default=0, alias="modulePosition", ge=0)
    segment_position: int = Field(default=0, alias="segmentPosition", ge=0)
    status: LessonCompletionStatus


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


def _lesson_summary(lesson: Lesson, *, assignment_count: int = 0) -> dict[str, object]:
    return {
        "id": str(lesson.id),
        "title": lesson.title,
        "status": lesson.status.value,
        "sourceType": lesson.source_type.value,
        "segmentCount": lesson.segment_count,
        "reviewSegmentCount": lesson.review_segment_count,
        "subject": lesson.subject,
        "assignmentCount": assignment_count,
        "estimatedMinutes": lesson.estimated_minutes,
        "createdAt": lesson.created_at,
    }


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
) -> list[dict[str, object]]:
    actor = await require_school_actor(session, principal)
    if actor.role == UserRole.STUDENT:
        rows = (
            await session.scalars(
                select(Lesson)
                .join(LessonAssignment, LessonAssignment.lesson_id == Lesson.id)
                .where(
                    LessonAssignment.student_id == actor.id,
                    LessonAssignment.status != "cancelled",
                    or_(
                        LessonAssignment.available_from.is_(None),
                        LessonAssignment.available_from <= datetime.now(UTC),
                    ),
                )
                .order_by(Lesson.created_at.desc())
            )
        ).all()
    else:
        rows = (
            await session.scalars(
                select(Lesson)
                .where(Lesson.school_id == actor.school_id)
                .order_by(Lesson.created_at.desc())
            )
        ).all()
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
    return [_lesson_summary(item, assignment_count=int(counts.get(item.id, 0))) for item in rows]


@router.get("/lessons/{lesson_id}", response_model=LessonDetailResponse)
async def lesson_detail(
    lesson_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    _, lesson = await _lesson_for_actor(lesson_id, principal, session)
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
        **_lesson_summary(lesson, assignment_count=int(assignment_count or 0)),
        "confirmationSummary": lesson.confirmation_summary,
        "segments": [
            {
                "id": str(item.id),
                "segmentKey": item.segment_key,
                "sequenceOrder": item.sequence_order,
                "contentType": item.content_type.value,
                "title": item.title,
                "body": item.body,
                "availableModalities": item.available_modalities,
                "comprehensionCheckpoints": checkpoint_payloads(
                    item.comprehension_checkpoints, segment_key=item.segment_key
                ),
                "textVariant": item.text_variant,
                "visualVariant": item.visual_variant,
                "audioVariant": item.audio_variant,
                "interactiveVariant": item.interactive_variant,
                "calculationVariant": item.calculation_variant,
                "needsReview": item.needs_review,
                "reviewReasons": item.review_reasons,
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
    return [
        {
            "id": str(item.id),
            "lesson": _lesson_summary(lesson),
            "studentId": str(item.student_id),
            "classId": str(item.class_id) if item.class_id else None,
            "status": item.status,
            "dueAt": item.due_at,
            "availableFrom": item.available_from,
            "assignedAt": item.assigned_at,
        }
        for item, lesson in rows
    ]


@router.post(
    "/assignments",
    response_model=AssignmentCreatedResponse,
    status_code=status.HTTP_201_CREATED,
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
    rows = [
        {
            "lesson_id": lesson_id,
            "student_id": student_id,
            "teacher_id": actor.id,
            "class_id": payload.class_id,
            "assignment_type": "class" if payload.class_id else "student",
            "due_at": payload.due_at,
            "available_from": payload.available_from,
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
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> None:
    await update_assignment(
        assignment_id,
        AssignmentPatch(status="cancelled"),
        principal,
        session,
    )


@router.post(
    "/lessons/{lesson_id}/session",
    response_model=LessonSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_lesson_session(
    lesson_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    actor, _ = await _lesson_for_actor(lesson_id, principal, session)
    if actor.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Student account required")
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
        return {"sessionId": str(existing.id), "resumed": True}
    record = LessonSession(
        id=uuid4(),
        student_id=actor.id,
        lesson_id=lesson_id,
        started_at=datetime.now(UTC),
        completion_status=LessonCompletionStatus.IN_PROGRESS,
    )
    session.add(record)
    await session.commit()
    return {"sessionId": str(record.id), "resumed": False}


@router.put("/lessons/{lesson_id}/progress", response_model=LessonProgressResponse)
async def save_lesson_progress(
    lesson_id: UUID,
    payload: ProgressWrite,
    principal: PrincipalDependency,
    session: DatabaseSession,
    request: Request,
) -> dict[str, object]:
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
    progress.status = payload.status
    progress.started_at = progress.started_at or lesson_session.started_at
    lesson_session.exit_position = str(payload.segment_position)
    if payload.status in {"completed", "exited"}:
        lesson_session.ended_at = datetime.now(UTC)
        lesson_session.completion_status = LessonCompletionStatus(payload.status)
    if payload.status == "completed":
        progress.completed_at = datetime.now(UTC)
        assignment = (
            await session.get(LessonAssignment, payload.assignment_id)
            if payload.assignment_id
            else None
        )
        if assignment and assignment.student_id == actor.id:
            assignment.status = "completed"
            assignment.completed_at = datetime.now(UTC)
    await session.commit()

    intelligence: dict[str, object] = {"status": "not_run"}
    if payload.status == "completed":
        worker = getattr(request.app.state, "post_lesson_worker", None)
        if isinstance(worker, PostLessonProcessingWorker):
            intelligence["status"] = await worker.enqueue(
                session_id=lesson_session.id,
                student_id=actor.id,
                completed_at=lesson_session.ended_at,
            )
        else:
            intelligence["status"] = "deferred"
    return {
        "lessonId": str(lesson_id),
        "status": progress.status,
        "modulePosition": progress.module_position,
        "segmentPosition": progress.segment_position,
        "intelligence": intelligence,
    }


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
    return {
        "student": {"id": str(actor.id), "firstName": actor.first_name},
        "assignments": due,
        "recentProgress": [
            {
                "lessonId": str(item.lesson_id),
                "status": item.status,
                "segmentPosition": item.segment_position,
                "updatedAt": item.updated_at,
            }
            for item in progress[:5]
        ],
    }


@router.get("/students/{student_id}/profile", response_model=StudentProfileResponse)
async def student_profile(
    student_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    await require_student_access(session, principal, student_id)
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
            "ageBand": student.age_band,
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
    openapi_extra={"security": []},
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


@router.post("/lessons/{lesson_id}/download", response_model=OfflineDownloadResponse)
async def create_offline_download(
    lesson_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
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
    manifest = {
        "lessonId": str(lesson_id),
        "version": 1,
        "segmentCount": len(package["segments"]),
        "generatedAt": datetime.now(UTC).isoformat(),
        "packageUrl": f"/api/v1/lessons/{lesson_id}/offline-package",
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


@router.get("/lessons/{lesson_id}/offline-package")
async def offline_package(
    lesson_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> Response:
    actor, lesson = await _lesson_for_actor(lesson_id, principal, session)
    if actor.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Student account required")
    payload = await _offline_package_payload(session, lesson_id)
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
                    "lessonId": str(lesson.id),
                    "version": 1,
                    "files": ["lesson.json"],
                },
                separators=(",", ":"),
            ),
        )
    filename = f"nevo-lesson-{lesson.id}.zip"
    return Response(
        content=output.getvalue(),
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
    try:
        parsed = await parser.parse(
            request=ContentParseRequest(
                title=payload.title,
                source_type=payload.source_type,
                source_text=payload.source_text,
                source_metadata={"subject": payload.subject} if payload.subject else {},
            ),
            requested_by_user_id=actor.id,
        )
        job.status = "ready"
        job.stage = "structure"
        job.structure = _upload_structure(parsed)
        job.completed_at = datetime.now(UTC)
        await session.commit()
    except Exception as error:
        job.status = "failed"
        job.error_message = str(error)[:1000]
        await session.commit()
    return {"uploadId": str(job.id), "status": job.status, "stage": job.stage}


@router.post("/uploads", response_model=UploadCreatedResponse, status_code=status.HTTP_201_CREATED)
async def staged_file_upload(
    principal: PrincipalDependency,
    session: DatabaseSession,
    parser: ParsingService,
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
    )


async def _ingest_one_file(
    *,
    file: UploadFile,
    filename: str,
    scope: str,
    subject: str | None,
    principal: PrincipalDependency,
    session: DatabaseSession,
    parser: ParsingService,
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
        SsoProvider.GOOGLE
        if payload.source_type == "google_drive"
        else SsoProvider.MICROSOFT
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
    parsed = await parser.parse(
        request=ContentParseRequest(
            title=_title_from_filename(blob.filename),
            source_type=LessonSourceType.PDF,
            pages=tuple(pages),
            source_metadata={"retryOfUploadId": str(upload_id)},
        ),
        requested_by_user_id=actor.id,
    )
    structure = _upload_structure(parsed)
    job.undo_stack = [*job.undo_stack, job.structure][-20:]
    job.structure = structure
    job.status = "ready"
    job.error_message = None
    await session.commit()
    return {
        "uploadId": str(upload_id),
        "lessonId": str(parsed.lesson_id),
        "pagesRetried": sorted(set(payload.page_numbers)),
        "structure": structure,
    }


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
        "structure": job.structure,
        "error": job.error_message,
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


async def _offline_package_payload(session: DatabaseSession, lesson_id: UUID) -> dict[str, object]:
    lesson = await session.get(Lesson, lesson_id)
    segments = (
        await session.scalars(
            select(LessonSegment)
            .where(LessonSegment.lesson_id == lesson_id)
            .order_by(LessonSegment.sequence_order)
        )
    ).all()
    if lesson is None:
        raise HTTPException(status_code=404, detail="Lesson not found")
    return {
        "id": str(lesson.id),
        "title": lesson.title,
        "version": lesson.parser_version,
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
                "comprehensionCheckpoints": checkpoint_payloads(
                    item.comprehension_checkpoints, segment_key=item.segment_key
                ),
            }
            for item in segments
        ],
    }


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
