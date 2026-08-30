import json
from datetime import UTC, datetime
from io import BytesIO
from typing import Annotated
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
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select

from nevo.api.auth import PrincipalDependency
from nevo.api.content import get_content_parsing_service
from nevo.api.dependencies import DatabaseSession
from nevo.api.frontend_unblockers import _extract_text, _source_type, _title_from_filename
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
    UploadStatusResponse,
    UploadStructureResponse,
)
from nevo.attention_flags.service import AttentionFlagDetectionService
from nevo.content_parsing.entities import ContentParseRequest
from nevo.content_parsing.service import ContentParsingService
from nevo.db.models.account import Class, StudentClassEnrollment, User
from nevo.db.models.attention_flag import AttentionFlag
from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.models.frontend_support import LessonAssignment
from nevo.db.models.learner_profile import LearnerProfile
from nevo.db.models.product import (
    LessonModule,
    LessonProgress,
    OfflineDownload,
    PostLessonProcessing,
    UploadJob,
)
from nevo.db.models.signal_event import LessonSession
from nevo.domain.accounts.vocabulary import UserRole
from nevo.domain.intelligence.vocabulary import LessonSourceType
from nevo.domain.signal_events.vocabulary import LessonCompletionStatus
from nevo.learner_profiles.profile_updates import PostLessonProfileUpdateService

router = APIRouter(prefix="/api/v1", tags=["learning product"])
ParsingService = Annotated[ContentParsingService, Depends(get_content_parsing_service)]
LessonUpload = Annotated[UploadFile, File()]
UploadScope = Annotated[str, Form(pattern="^(lesson|unit|term)$")]
StudentFilter = Annotated[UUID | None, Query(alias="studentId")]
ClassFilter = Annotated[UUID | None, Query(alias="classId")]


class AssignmentPatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    due_at: datetime | None = Field(default=None, alias="dueAt")
    status: str | None = Field(default=None, pattern="^(assigned|cancelled)$")


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


class ProgressWrite(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_id: UUID = Field(alias="sessionId")
    assignment_id: UUID | None = Field(default=None, alias="assignmentId")
    module_position: int = Field(default=0, alias="modulePosition", ge=0)
    segment_position: int = Field(default=0, alias="segmentPosition", ge=0)
    status: str = Field(pattern="^(in_progress|completed|exited)$")


class UploadRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str = Field(min_length=1, max_length=255)
    filename: str = Field(min_length=1, max_length=255)
    scope: str = Field(default="lesson", pattern="^(lesson|unit|term)$")
    source_type: LessonSourceType = Field(alias="sourceType")
    source_text: str = Field(alias="sourceText", min_length=1)


class UploadStructureWrite(BaseModel):
    structure: dict[str, object]


def _lesson_summary(lesson: Lesson) -> dict[str, object]:
    return {
        "id": str(lesson.id),
        "title": lesson.title,
        "status": lesson.status.value,
        "sourceType": lesson.source_type.value,
        "segmentCount": lesson.segment_count,
        "reviewSegmentCount": lesson.review_segment_count,
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
    return [_lesson_summary(item) for item in rows]


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
    return {
        **_lesson_summary(lesson),
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
                "comprehensionCheckpoints": item.comprehension_checkpoints,
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
        query = query.where(LessonAssignment.student_id == actor.id)
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
    created = []
    for lesson_id in payload.lesson_ids:
        for student_id in student_ids:
            record = LessonAssignment(
                lesson_id=lesson_id,
                student_id=student_id,
                teacher_id=actor.id,
                class_id=payload.class_id,
                assignment_type="class" if payload.class_id else "student",
                due_at=payload.due_at,
            )
            session.add(record)
            await session.flush()
            created.append(str(record.id))
    await session.commit()
    return {"assignmentIds": created, "createdCount": len(created)}


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
    if payload.status is not None:
        record.status = payload.status
    await session.commit()
    return {"id": str(record.id), "status": record.status, "dueAt": record.due_at}


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
        processed = await session.get(PostLessonProcessing, lesson_session.id)
        if processed is not None:
            intelligence["status"] = "already_completed"
            return {
                "lessonId": str(lesson_id),
                "status": progress.status,
                "modulePosition": progress.module_position,
                "segmentPosition": progress.segment_position,
                "intelligence": intelligence,
            }
        profile_service = getattr(request.app.state, "post_lesson_profile_update_service", None)
        flag_service = getattr(request.app.state, "attention_flag_detection_service", None)
        try:
            if isinstance(profile_service, PostLessonProfileUpdateService):
                profile_result = await profile_service.update_after_lesson(
                    student_id=actor.id,
                    lesson_session_id=lesson_session.id,
                    requested_by_user_id=actor.id,
                )
                intelligence["profileUpdate"] = profile_result.status.value
            if isinstance(flag_service, AttentionFlagDetectionService):
                flag_result = await flag_service.evaluate_student(
                    student_id=actor.id,
                    requested_by_user_id=actor.id,
                )
                intelligence["attention"] = flag_result.status
            session.add(
                PostLessonProcessing(
                    session_id=lesson_session.id,
                    student_id=actor.id,
                )
            )
            await session.commit()
            intelligence["status"] = "completed"
        except Exception:
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
                "engineConfig": student.engine_config,
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
)
async def connect_by_class_code(
    class_code: str,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    student = await actor_user(session, principal)
    if student.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Student account required")
    school_class = await session.scalar(
        select(Class).where(func.lower(Class.class_code) == class_code.casefold())
    )
    if school_class is None or school_class.school_id != student.school_id:
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
    return {"classId": str(school_class.id), "status": "connected"}


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
            ),
            requested_by_user_id=actor.id,
        )
        segment_ids = [str(item.segment_key) for item in parsed.segments]
        modules = []
        for index in range(0, len(segment_ids), 5):
            modules.append(
                {
                    "title": f"Module {index // 5 + 1}",
                    "sequenceOrder": index // 5 + 1,
                    "segmentIds": segment_ids[index : index + 5],
                }
            )
        job.status = "ready"
        job.stage = "structure"
        job.structure = {
            "lessonId": str(parsed.lesson_id),
            "modules": modules,
            "reviewNotes": list(parsed.review_notes),
        }
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
) -> dict[str, object]:
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Lesson file exceeds 50 MB")
    filename = file.filename or "lesson.txt"
    source_text = _extract_text(filename, content)
    if not source_text.strip():
        raise HTTPException(status_code=400, detail="No readable lesson text was found")
    return await staged_upload(
        UploadRequest(
            title=_title_from_filename(filename),
            filename=filename,
            scope=scope,
            sourceType=_source_type(filename),
            sourceText=source_text,
        ),
        principal,
        session,
        parser,
    )


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
    return {
        "id": str(job.id),
        "status": job.status,
        "stage": job.stage,
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
    job.structure = payload.structure
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
                "modalityVariants": item.modality_variants,
                "comprehensionCheckpoints": item.comprehension_checkpoints,
            }
            for item in segments
        ],
    }


@router.post("/uploads/{upload_id}/confirm", response_model=UploadConfirmedResponse)
async def confirm_upload(
    upload_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    actor = await require_school_actor(session, principal)
    job = await session.get(UploadJob, upload_id)
    if job is None or job.school_id != actor.school_id:
        raise HTTPException(status_code=404, detail="Upload not found")
    lesson_id = job.structure.get("lessonId")
    if not lesson_id:
        raise HTTPException(status_code=409, detail="Upload has no parsed lesson")
    await session.execute(
        delete(LessonModule).where(LessonModule.lesson_id == UUID(str(lesson_id)))
    )
    module_items = job.structure.get("modules", [])
    if not isinstance(module_items, list):
        raise HTTPException(status_code=422, detail="Modules must be a list")
    for item in module_items:
        if not isinstance(item, dict):
            continue
        session.add(
            LessonModule(
                lesson_id=UUID(str(lesson_id)),
                title=str(item.get("title") or "Module"),
                recap=item.get("recap"),
                preview=item.get("preview"),
                sequence_order=int(item.get("sequenceOrder") or 1),
                segment_ids=(
                    list(segment_ids)
                    if isinstance((segment_ids := item.get("segmentIds")), list)
                    else []
                ),
            )
        )
    job.status = "confirmed"
    job.stage = "complete"
    await session.commit()
    return {"lessonId": str(lesson_id), "status": job.status}
