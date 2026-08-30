import hashlib
import re
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Annotated
from uuid import UUID
from zipfile import ZipFile

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import func, or_, select, update

from nevo.api.auth import PrincipalDependency
from nevo.api.content import (
    ParseContentResponse,
    get_content_parsing_service,
)
from nevo.api.dependencies import DatabaseSession
from nevo.api.permissions import RequireScope
from nevo.api.privacy import is_private_interaction_key
from nevo.api.product_common import (
    actor_user,
    require_class_access,
    require_school_actor,
    require_student_access,
)
from nevo.content_parsing.entities import ContentParseRequest, SourcePage
from nevo.content_parsing.service import ContentParsingService
from nevo.db.models.account import Class, School, StudentClassEnrollment, User
from nevo.db.models.attention_flag import AttentionFlag, InterventionRecommendation
from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.models.frontend_support import (
    Concept,
    LessonAssignment,
    Message,
    MessageThread,
    Notification,
    PasswordResetToken,
)
from nevo.db.models.learner_profile import LearnerProfile
from nevo.db.models.signal_event import LessonSession
from nevo.domain.accounts.vocabulary import UserRole, UserStatus
from nevo.domain.permissions.vocabulary import PermissionScope
from nevo.permissions.entities import PermissionSnapshot

router = APIRouter()
TeacherScope = Annotated[PermissionSnapshot, Depends(RequireScope(PermissionScope.TEACHER))]
OversightScope = Annotated[PermissionSnapshot, Depends(RequireScope(PermissionScope.OVERSIGHT))]
ContentParsingDependency = Annotated[
    ContentParsingService,
    Depends(get_content_parsing_service),
]
UploadedLessonFile = Annotated[UploadFile, File()]
SchoolIdQuery = Annotated[UUID | None, Query(alias="schoolId")]
StudentIdQuery = Annotated[UUID | None, Query(alias="studentId")]
ClassIdQuery = Annotated[UUID | None, Query(alias="classId")]


class SchoolSummary(BaseModel):
    id: UUID
    name: str
    slug: str | None
    code: str | None


class CurrentUserResponse(BaseModel):
    user_id: UUID
    role: str
    first_name: str | None
    last_name: str | None
    display_name: str
    email: str | None
    school: SchoolSummary | None
    subjects: list[str] = Field(default_factory=list)


class ClassStudentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    student_id: UUID
    first_name: str | None
    last_name: str | None
    display_name: str
    login_identifier: str | None
    status: str
    profile_status: str = Field(alias="profileStatus")
    latest_session_at: datetime | None = Field(alias="latestSessionAt")


class ConceptResponse(BaseModel):
    id: UUID
    name: str
    subject: str | None = None


class LessonSegmentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    segment_key: str = Field(alias="segmentKey")
    content_type: str = Field(alias="contentType")
    sequence_order: int = Field(alias="sequenceOrder")
    title: str | None
    body: str
    available_modalities: list[str] = Field(alias="availableModalities")
    comprehension_checkpoints: list[dict[str, object]] = Field(alias="comprehensionCheckpoints")
    needs_review: bool = Field(alias="needsReview")
    review_reasons: list[str] = Field(alias="reviewReasons")


class LessonSummaryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    title: str
    source_type: str = Field(alias="sourceType")
    status: str
    segment_count: int = Field(alias="segmentCount")
    review_segment_count: int = Field(alias="reviewSegmentCount")
    created_at: datetime = Field(alias="createdAt")


class LessonDetailResponse(LessonSummaryResponse):
    confirmation_summary: str | None = Field(alias="confirmationSummary")
    segments: list[LessonSegmentResponse]


class LessonAssignmentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    lesson_id: UUID = Field(alias="lessonId")
    class_id: UUID | None = Field(default=None, alias="classId")
    student_ids: list[UUID] = Field(default_factory=list, alias="studentIds")
    due_at: datetime | None = Field(default=None, alias="dueAt")


class LessonAssignmentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    assignment_ids: list[UUID] = Field(alias="assignmentIds")
    created_count: int = Field(alias="createdCount")


class NotificationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    notification_id: UUID = Field(alias="notificationId")
    recipient_id: UUID = Field(alias="recipientId")
    recipient_role: str = Field(alias="recipientRole")
    type: str
    title: str
    description: str
    read: bool
    created_at: datetime = Field(alias="createdAt")
    navigates_to: str | None = Field(alias="navigatesTo")


class NotificationListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    notifications: list[NotificationResponse]
    unread_count: int = Field(alias="unreadCount")


class UnreadCountResponse(BaseModel):
    count: int


class MessageThreadResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    thread_id: UUID = Field(alias="threadId")
    recipient_type: str = Field(alias="recipientType")
    recipient_id: UUID | None = Field(alias="recipientId")
    title: str
    latest_preview: str | None = Field(alias="latestPreview")
    last_message_at: datetime = Field(alias="lastMessageAt")


class MessageResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message_id: UUID = Field(alias="messageId")
    thread_id: UUID = Field(alias="threadId")
    sender_id: UUID | None = Field(alias="senderId")
    sender_name: str | None = Field(alias="senderName")
    content: str
    created_at: datetime = Field(alias="createdAt")


class MessageThreadListResponse(BaseModel):
    threads: list[MessageThreadResponse]
    total: int


class MessageListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    thread_id: UUID = Field(alias="threadId")
    messages: list[MessageResponse]


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    recipient_id: UUID = Field(alias="recipientId")
    recipient_type: str = Field(alias="recipientType", pattern="^(student|class)$")
    content: str = Field(min_length=1, max_length=5_000)


class BaselineSubmitRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(alias="sessionId", min_length=1, max_length=120)
    features: list[dict[str, object]] = Field(default_factory=list, max_length=500)


class BaselineSubmitResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: str
    feature_count: int = Field(alias="featureCount")


class BaselinePromptResponse(BaseModel):
    dimension: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetReceipt(BaseModel):
    status: str
    message: str


class UpdateSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="allow")


class SettingsResponse(BaseModel):
    settings: dict[str, object]


@router.get(
    "/api/v1/users/me",
    response_model=CurrentUserResponse,
    tags=["authentication"],
)
async def current_user_profile(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> CurrentUserResponse:
    user = await session.get(User, principal.user_id)
    school = await session.get(School, user.school_id) if user and user.school_id else None
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return CurrentUserResponse(
        user_id=user.id,
        role=user.role.value,
        first_name=user.first_name,
        last_name=user.last_name,
        display_name=_display_name(user),
        email=user.email,
        school=(
            SchoolSummary(
                id=school.id,
                name=school.name,
                slug=school.school_url_slug,
                code=school.school_code,
            )
            if school
            else None
        ),
        subjects=_subjects_for_user(user),
    )


@router.get(
    "/api/v1/classes/{class_id}/students",
    response_model=list[ClassStudentResponse],
    tags=["school administration"],
)
async def class_students(
    class_id: UUID,
    actor: TeacherScope,
    session: DatabaseSession,
) -> list[ClassStudentResponse]:
    school_class = await session.get(Class, class_id)
    if school_class is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Class not found")
    if actor.school_id != school_class.school_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Class is outside your school",
        )
    rows = (
        await session.execute(
            select(User, LearnerProfile.id, func.max(LessonSession.started_at))
            .join(StudentClassEnrollment, StudentClassEnrollment.student_id == User.id)
            .outerjoin(LearnerProfile, LearnerProfile.learner_id == User.id)
            .outerjoin(LessonSession, LessonSession.student_id == User.id)
            .where(
                StudentClassEnrollment.class_id == class_id,
                User.role == UserRole.STUDENT,
                User.status != UserStatus.DEACTIVATED,
            )
            .group_by(User.id, LearnerProfile.id)
            .order_by(User.first_name, User.last_name, User.login_identifier)
        )
    ).all()
    return [
        ClassStudentResponse(
            student_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            display_name=_display_name(user),
            login_identifier=user.login_identifier,
            status=user.status.value,
            profileStatus="observed" if profile_id else "not_observed_yet",
            latestSessionAt=latest_session_at,
        )
        for user, profile_id, latest_session_at in rows
    ]


@router.get("/api/concepts", response_model=list[ConceptResponse], tags=["content"])
async def concepts(
    session: DatabaseSession,
    ids: str | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1, max_length=120),
) -> list[ConceptResponse]:
    query = select(Concept).order_by(Concept.name).limit(100)
    if ids:
        concept_ids = [_uuid(item) for item in ids.split(",") if item.strip()]
        query = select(Concept).where(Concept.id.in_(concept_ids)).order_by(Concept.name)
    elif search:
        query = query.where(Concept.name.ilike(f"%{search}%"))
    records = (await session.scalars(query)).all()
    return [ConceptResponse(id=item.id, name=item.name, subject=item.subject) for item in records]


@router.get(
    "/api/concepts/{concept_id}",
    response_model=ConceptResponse,
    tags=["content"],
)
async def concept(concept_id: UUID, session: DatabaseSession) -> ConceptResponse:
    record = await session.get(Concept, concept_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Concept not found")
    return ConceptResponse(id=record.id, name=record.name, subject=record.subject)


@router.get(
    "/api/content/lessons",
    response_model=list[LessonSummaryResponse],
    operation_id="content_list_lessons_compatibility",
    tags=["content"],
)
async def list_lessons(
    principal: PrincipalDependency,
    session: DatabaseSession,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[LessonSummaryResponse]:
    user = await session.get(User, principal.user_id)
    query = select(Lesson)
    if user and user.role == UserRole.STUDENT:
        query = query.join(LessonAssignment, LessonAssignment.lesson_id == Lesson.id).where(
            LessonAssignment.student_id == user.id,
            LessonAssignment.status != "cancelled",
        )
    elif user and user.school_id:
        query = query.where(or_(Lesson.school_id == user.school_id, Lesson.school_id.is_(None)))
    query = query.order_by(Lesson.created_at.desc()).limit(limit)
    lessons = (await session.scalars(query)).all()
    return [_lesson_summary(item) for item in lessons]


@router.get(
    "/api/content/lessons/{lesson_id}",
    response_model=LessonDetailResponse,
    operation_id="content_lesson_detail_compatibility",
    tags=["content"],
)
async def lesson_detail(
    lesson_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> LessonDetailResponse:
    actor = await require_school_actor(session, principal)
    lesson = await session.get(Lesson, lesson_id)
    if lesson is None or (lesson.school_id is not None and lesson.school_id != actor.school_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found")
    segments = (
        await session.scalars(
            select(LessonSegment)
            .where(LessonSegment.lesson_id == lesson_id)
            .order_by(LessonSegment.sequence_order)
        )
    ).all()
    return LessonDetailResponse(
        **_lesson_summary(lesson).model_dump(by_alias=True),
        confirmationSummary=lesson.confirmation_summary,
        segments=[
            LessonSegmentResponse(
                id=item.id,
                segmentKey=item.segment_key,
                contentType=item.content_type.value,
                sequenceOrder=item.sequence_order,
                title=item.title,
                body=item.body,
                availableModalities=list(item.available_modalities),
                comprehensionCheckpoints=list(item.comprehension_checkpoints),
                needsReview=item.needs_review,
                reviewReasons=list(item.review_reasons),
            )
            for item in segments
        ],
    )


@router.post(
    "/api/content/upload",
    response_model=ParseContentResponse,
    tags=["content"],
)
async def upload_content(
    principal: PrincipalDependency,
    session: DatabaseSession,
    service: ContentParsingDependency,
    file: UploadedLessonFile,
) -> ParseContentResponse:
    del session
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    content = await file.read()
    source_text = _extract_text(file.filename or "lesson.txt", content)
    if not source_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nevo could not extract readable lesson text from this file.",
        )
    result = await service.parse(
        request=ContentParseRequest(
            title=_title_from_filename(file.filename),
            source_type=_source_type(file.filename),
            source_text=source_text,
            pages=(SourcePage(page_number=1, text=source_text),),
            source_metadata={
                "fileName": file.filename,
                "contentType": file.content_type,
                "byteLength": len(content),
            },
        ),
        requested_by_user_id=principal.user_id,
    )
    return ParseContentResponse.from_result(result)


@router.post(
    "/api/v1/lesson-assignments",
    response_model=LessonAssignmentResponse,
    status_code=201,
    tags=["learning product"],
)
async def create_lesson_assignments(
    payload: LessonAssignmentRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> LessonAssignmentResponse:
    user = await require_school_actor(
        session,
        principal,
        roles={"teacher", "senco_admin", "other_admin"},
    )
    lesson = await session.get(Lesson, payload.lesson_id)
    if lesson is None or lesson.school_id != user.school_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found")
    student_ids = list(payload.student_ids)
    if payload.class_id is not None:
        await require_class_access(session, user, payload.class_id)
        rows = await session.scalars(
            select(StudentClassEnrollment.student_id).where(
                StudentClassEnrollment.class_id == payload.class_id
            )
        )
        student_ids.extend(rows.all())
    unique_student_ids = sorted(set(student_ids), key=str)
    for student_id in unique_student_ids:
        await require_student_access(session, principal, student_id)
    created: list[UUID] = []
    async with session.begin_nested():
        for student_id in unique_student_ids:
            record = LessonAssignment(
                lesson_id=payload.lesson_id,
                student_id=student_id,
                teacher_id=principal.user_id,
                class_id=payload.class_id,
                assignment_type="class" if payload.class_id else "student",
                due_at=payload.due_at,
            )
            session.add(record)
            await session.flush()
            created.append(record.id)
    await session.commit()
    return LessonAssignmentResponse(assignmentIds=created, createdCount=len(created))


@router.get(
    "/api/notifications",
    response_model=NotificationListResponse,
    tags=["notifications"],
)
async def list_notifications(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> NotificationListResponse:
    records = (
        await session.scalars(
            select(Notification)
            .where(Notification.recipient_id == principal.user_id)
            .order_by(Notification.created_at.desc())
            .limit(100)
        )
    ).all()
    return NotificationListResponse(
        notifications=[_notification(item) for item in records],
        unreadCount=sum(1 for item in records if not item.read),
    )


@router.get(
    "/api/notifications/unread-count",
    response_model=UnreadCountResponse,
    tags=["notifications"],
)
async def unread_count(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> UnreadCountResponse:
    count = await session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.recipient_id == principal.user_id, Notification.read.is_(False))
    )
    return UnreadCountResponse(count=int(count or 0))


@router.post(
    "/api/notifications/{notification_id}/read",
    status_code=204,
    tags=["notifications"],
)
async def mark_notification_read(
    notification_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> None:
    result = await session.execute(
        update(Notification)
        .where(Notification.id == notification_id, Notification.recipient_id == principal.user_id)
        .values(read=True, updated_at=datetime.now(UTC))
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    await session.commit()


@router.get(
    "/api/messages/threads",
    response_model=MessageThreadListResponse,
    tags=["messaging"],
)
async def message_threads(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> MessageThreadListResponse:
    user = await session.get(User, principal.user_id)
    if user is None or user.school_id is None:
        return MessageThreadListResponse(threads=[], total=0)
    query = select(MessageThread).where(MessageThread.school_id == user.school_id)
    if user.role == UserRole.STUDENT:
        query = query.where(MessageThread.student_id == user.id)
    records = (await session.scalars(query.order_by(MessageThread.last_message_at.desc()))).all()
    threads = [await _thread_response(session, item) for item in records]
    return MessageThreadListResponse(threads=threads, total=len(threads))


@router.get(
    "/api/messages/threads/{thread_id}",
    response_model=MessageListResponse,
    tags=["messaging"],
)
async def thread_messages(
    thread_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> MessageListResponse:
    thread = await _require_thread_access(session, principal.user_id, thread_id)
    rows = (
        await session.execute(
            select(Message, User)
            .outerjoin(User, User.id == Message.sender_id)
            .where(Message.thread_id == thread.id)
            .order_by(Message.created_at)
        )
    ).all()
    return MessageListResponse(
        threadId=thread.id,
        messages=[
            MessageResponse(
                messageId=message.id,
                threadId=message.thread_id,
                senderId=message.sender_id,
                senderName=_display_name(sender) if sender else None,
                content=message.content,
                createdAt=message.created_at,
            )
            for message, sender in rows
        ],
    )


@router.post(
    "/api/messages",
    response_model=MessageResponse,
    status_code=201,
    tags=["messaging"],
)
async def send_message(
    payload: SendMessageRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> MessageResponse:
    user = await session.get(User, principal.user_id)
    if user is None or user.school_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="School context required")
    thread = await _find_or_create_thread(session, user, payload)
    message = Message(thread_id=thread.id, sender_id=user.id, content=payload.content.strip())
    thread.latest_preview = payload.content.strip()[:255]
    thread.last_message_at = datetime.now(UTC)
    session.add(message)
    await session.flush()
    await session.commit()
    return MessageResponse(
        messageId=message.id,
        threadId=thread.id,
        senderId=user.id,
        senderName=_display_name(user),
        content=message.content,
        createdAt=message.created_at,
    )


@router.post(
    "/api/baseline/submit",
    response_model=BaselineSubmitResponse,
    tags=["intelligence"],
)
async def submit_baseline(
    payload: BaselineSubmitRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> BaselineSubmitResponse:
    features = payload.features
    leaked = {
        key
        for feature in features
        for key in feature
        if is_private_interaction_key(key)
    }
    if leaked:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Raw interaction fields are device-only. Submit reduced "
                "aggregate baseline features."
            ),
        )
    await session.execute(
        update(User)
        .where(User.id == principal.user_id)
        .values(
            # Dynamic attribute exists in production DB from earlier baseline work.
            baseline_profile={
                "session_id": payload.session_id,
                "feature_count": len(features),
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
    )
    await session.commit()
    return BaselineSubmitResponse(status="accepted", featureCount=len(features))


@router.get(
    "/api/baseline/recalibrate-prompt/{student_id}",
    response_model=BaselinePromptResponse,
    tags=["intelligence"],
)
async def recalibrate_prompt(
    student_id: UUID,
    principal: PrincipalDependency,
) -> BaselinePromptResponse:
    if principal.role == "student" and principal.user_id != student_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Students can view only their own warm-up prompt",
        )
    dimensions = ("working_memory", "attention", "reading_fluency", "number_sense")
    index = int(hashlib.sha256(str(student_id).encode()).hexdigest(), 16) % len(dimensions)
    return BaselinePromptResponse(dimension=dimensions[index])


@router.get("/api/analytics/schools", tags=["admin"])
async def school_health(actor: OversightScope) -> dict[str, object]:
    return {
        "schoolId": str(actor.school_id) if actor.school_id else None,
        "status": "ready",
        "summary": "School data surfaces are available.",
    }


@router.get("/api/analytics/outcomes", tags=["admin"])
async def outcomes(
    actor: OversightScope,
    school_id: SchoolIdQuery = None,
) -> dict[str, object]:
    return {
        "schoolId": str(school_id or actor.school_id) if (school_id or actor.school_id) else None,
        "outcomes": [],
    }


@router.get("/api/intelligence/profile/{student_id}", tags=["intelligence"])
async def learner_profile_alias(
    student_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    await require_student_access(session, principal, student_id)
    profile = await session.scalar(
        select(LearnerProfile).where(LearnerProfile.learner_id == student_id)
    )
    if profile is None:
        return {"studentId": str(student_id), "status": "not_observed_yet"}
    return {
        "studentId": str(student_id),
        "status": "observed",
        "workingMemoryCapacity": profile.working_memory_capacity,
        "attentionSpan": profile.attention_span,
        "observedEventCount": profile.observed_event_count,
    }


@router.get("/api/intelligence/flags", tags=["intelligence"])
async def flags_alias(
    principal: PrincipalDependency,
    session: DatabaseSession,
    student_id: StudentIdQuery = None,
    class_id: ClassIdQuery = None,
) -> list[dict[str, object]]:
    actor = await actor_user(session, principal)
    query = select(AttentionFlag).order_by(AttentionFlag.generated_at.desc()).limit(50)
    if class_id is not None:
        await require_class_access(session, actor, class_id)
        query = query.join(
            StudentClassEnrollment,
            StudentClassEnrollment.student_id == AttentionFlag.student_id,
        ).where(StudentClassEnrollment.class_id == class_id)
    if student_id is not None:
        await require_student_access(session, principal, student_id)
        query = query.where(AttentionFlag.student_id == student_id)
    elif principal.role == "student":
        query = query.where(AttentionFlag.student_id == principal.user_id)
    else:
        query = query.join(User, User.id == AttentionFlag.student_id).where(
            User.school_id == actor.school_id
        )
    rows = (await session.scalars(query)).all()
    return [
        {
            "id": str(item.id),
            "studentId": str(item.student_id),
            "flagType": item.flag_type.value,
            "description": item.description,
            "generatedAt": item.generated_at.isoformat(),
            "acknowledged": item.acknowledged_at is not None,
        }
        for item in rows
    ]


@router.get(
    "/api/intelligence/recommendations/{student_id}",
    tags=["intelligence"],
)
async def recommendations_alias(
    student_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> list[dict[str, object]]:
    await require_student_access(session, principal, student_id)
    rows = (
        await session.scalars(
            select(InterventionRecommendation)
            .where(InterventionRecommendation.student_id == student_id)
            .order_by(InterventionRecommendation.generated_at.desc())
            .limit(20)
        )
    ).all()
    return [
        {
            "id": str(item.id),
            "studentId": str(item.student_id),
            "recommendationText": item.recommendation_text,
            "generatedAt": item.generated_at.isoformat(),
        }
        for item in rows
    ]


@router.post(
    "/api/v1/auth/forgot-password",
    response_model=ResetReceipt,
    operation_id="authentication_forgot_password_compatibility",
    tags=["authentication"],
)
@router.post(
    "/api/v1/auth/password-reset/request",
    response_model=ResetReceipt,
    operation_id="authentication_password_reset_request_compatibility",
    tags=["authentication"],
)
async def request_password_reset(
    payload: ForgotPasswordRequest,
    session: DatabaseSession,
) -> ResetReceipt:
    user = await session.scalar(select(User).where(func.lower(User.email) == payload.email.lower()))
    if user is not None:
        token = hashlib.sha256(f"{user.id}:{datetime.now(UTC).isoformat()}".encode()).hexdigest()
        session.add(
            PasswordResetToken(
                user_id=user.id,
                token_digest=hashlib.sha256(token.encode()).hexdigest(),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        await session.commit()
    return ResetReceipt(
        status="accepted",
        message="If the account exists, Nevo will send password reset instructions.",
    )


@router.get(
    "/api/settings/me",
    response_model=SettingsResponse,
    tags=["school administration"],
)
async def get_settings(principal: PrincipalDependency) -> SettingsResponse:
    return SettingsResponse(settings={"userId": str(principal.user_id), "preferences": {}})


@router.put(
    "/api/settings/me",
    response_model=SettingsResponse,
    tags=["school administration"],
)
async def update_settings(
    payload: UpdateSettingsRequest,
    principal: PrincipalDependency,
) -> SettingsResponse:
    return SettingsResponse(
        settings={"userId": str(principal.user_id), "preferences": payload.model_extra or {}}
    )


def _display_name(user: User) -> str:
    name = " ".join(part for part in (user.first_name, user.last_name) if part)
    return name or user.email or user.login_identifier or "Nevo user"


def _subjects_for_user(user: User) -> list[str]:
    del user
    return []


def _uuid(value: str) -> UUID:
    try:
        return UUID(value.strip())
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid concept id",
        ) from error


def _lesson_summary(lesson: Lesson) -> LessonSummaryResponse:
    return LessonSummaryResponse(
        id=lesson.id,
        title=lesson.title,
        sourceType=lesson.source_type.value,
        status=lesson.status.value,
        segmentCount=lesson.segment_count,
        reviewSegmentCount=lesson.review_segment_count,
        createdAt=lesson.created_at,
    )


def _notification(item: Notification) -> NotificationResponse:
    return NotificationResponse(
        notificationId=item.id,
        recipientId=item.recipient_id,
        recipientRole=item.recipient_role,
        type=item.type,
        title=item.title,
        description=item.description,
        read=item.read,
        createdAt=item.created_at,
        navigatesTo=item.navigates_to,
    )


def _title_from_filename(filename: str | None) -> str:
    if not filename:
        return "Uploaded lesson"
    title = re.sub(r"\.[A-Za-z0-9]+$", "", filename).replace("_", " ").replace("-", " ").strip()
    return title or "Uploaded lesson"


def _source_type(filename: str | None):
    from nevo.domain.intelligence.vocabulary import LessonSourceType

    suffix = (filename or "").lower().rsplit(".", 1)[-1]
    return {
        "pdf": LessonSourceType.PDF,
        "docx": LessonSourceType.WORD,
        "pptx": LessonSourceType.POWERPOINT,
        "txt": LessonSourceType.TEXT,
        "md": LessonSourceType.TEXT,
    }.get(suffix, LessonSourceType.TEXT)


def _extract_text(filename: str, content: bytes) -> str:
    suffix = filename.lower().rsplit(".", 1)[-1]
    if suffix in {"txt", "md"}:
        return content.decode("utf-8", errors="ignore")
    if suffix == "pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(content))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as error:
            raise HTTPException(status_code=400, detail="Could not read PDF text") from error
    if suffix in {"docx", "pptx"}:
        return _extract_office_text(content)
    raise HTTPException(status_code=400, detail="Upload a TXT, PDF, DOCX, or PPTX file")


def _extract_office_text(content: bytes) -> str:
    try:
        with ZipFile(BytesIO(content)) as archive:
            texts = []
            for name in archive.namelist():
                if not name.endswith(".xml"):
                    continue
                if not (name.startswith("word/") or name.startswith("ppt/")):
                    continue
                raw = archive.read(name).decode("utf-8", errors="ignore")
                texts.append(re.sub(r"<[^>]+>", " ", raw))
    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail="Could not read Office document text",
        ) from error
    return re.sub(r"\s+", " ", "\n".join(texts)).strip()


async def _thread_response(session, thread: MessageThread) -> MessageThreadResponse:
    title = "Conversation"
    recipient_id = None
    if thread.recipient_type == "student" and thread.student_id:
        student = await session.get(User, thread.student_id)
        title = _display_name(student) if student else "Student conversation"
        recipient_id = thread.student_id
    elif thread.recipient_type == "class" and thread.class_id:
        school_class = await session.get(Class, thread.class_id)
        title = school_class.name if school_class else "Class conversation"
        recipient_id = thread.class_id
    return MessageThreadResponse(
        threadId=thread.id,
        recipientType=thread.recipient_type,
        recipientId=recipient_id,
        title=title,
        latestPreview=thread.latest_preview,
        lastMessageAt=thread.last_message_at,
    )


async def _require_thread_access(session, user_id: UUID, thread_id: UUID) -> MessageThread:
    user = await session.get(User, user_id)
    thread = await session.get(MessageThread, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    if user is None or user.school_id != thread.school_id:
        raise HTTPException(status_code=403, detail="Thread is outside your school")
    if user.role == UserRole.STUDENT and thread.student_id != user.id:
        raise HTTPException(status_code=403, detail="Thread is not available to this student")
    return thread


async def _find_or_create_thread(
    session,
    user: User,
    payload: SendMessageRequest,
) -> MessageThread:
    query = select(MessageThread).where(
        MessageThread.school_id == user.school_id,
        MessageThread.recipient_type == payload.recipient_type,
    )
    if payload.recipient_type == "student":
        student = await session.get(User, payload.recipient_id)
        if (
            student is None
            or student.school_id != user.school_id
            or student.role != UserRole.STUDENT
        ):
            raise HTTPException(status_code=404, detail="Student not found")
        query = query.where(MessageThread.student_id == payload.recipient_id)
    else:
        school_class = await session.get(Class, payload.recipient_id)
        if school_class is None or school_class.school_id != user.school_id:
            raise HTTPException(status_code=404, detail="Class not found")
        query = query.where(MessageThread.class_id == payload.recipient_id)
    thread = await session.scalar(query)
    if thread is not None:
        return thread
    thread = MessageThread(
        school_id=user.school_id,
        recipient_type=payload.recipient_type,
        student_id=payload.recipient_id if payload.recipient_type == "student" else None,
        class_id=payload.recipient_id if payload.recipient_type == "class" else None,
        created_by_id=user.id,
        latest_preview=None,
        last_message_at=datetime.now(UTC),
    )
    session.add(thread)
    await session.flush()
    return thread
