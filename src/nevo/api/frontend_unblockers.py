import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Annotated
from uuid import UUID
from zipfile import ZipFile

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from nevo.api.auth import PrincipalDependency
from nevo.api.content import (
    ParseContentResponse,
    get_content_parsing_service,
)
from nevo.api.dependencies import DatabaseSession
from nevo.api.pagination import (
    DEFAULT_LIMIT,
    LimitQuery,
    OffsetQuery,
    has_more,
    paginate,
    set_page_headers,
)
from nevo.api.permissions import RequireScope
from nevo.api.privacy import is_private_interaction_key
from nevo.api.product_common import (
    actor_user,
    can_access_student,
    require_class_access,
    require_school_actor,
    require_student_access,
)
from nevo.api.response_models import (
    AttentionFlagResponse,
    InterventionResponse,
    OutcomesResponse,
    ProfileAliasResponse,
    SchoolHealthResponse,
)
from nevo.api.response_models import (
    LessonModuleResponse as SharedLessonModuleResponse,
)
from nevo.content_parsing.entities import ContentParseRequest, SourcePage
from nevo.content_parsing.service import ContentParsingService
from nevo.db.models.account import Class, School, StudentClassEnrollment, User
from nevo.db.models.attention_flag import AttentionFlag, InterventionRecommendation
from nevo.db.models.consent import ParentLink
from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.models.frontend_support import (
    Concept,
    LessonAssignment,
    Message,
    MessageThread,
    MessageThreadRead,
    Notification,
    PasswordResetToken,
)
from nevo.db.models.learner_profile import LearnerProfile
from nevo.db.models.product import LessonModule
from nevo.db.models.signal_event import LessonSession, SignalEvent
from nevo.db.models.teacher_assignment import TeacherClassAssignment
from nevo.domain.accounts.vocabulary import (
    MessageRecipientType,
    NotificationType,
    UserRole,
    UserStatus,
)
from nevo.domain.intelligence.vocabulary import (
    ContentParseStatus,
    LessonContentType,
    LessonSourceType,
    SegmentReviewReason,
)
from nevo.domain.permissions.vocabulary import PermissionScope
from nevo.domain.signal_events.vocabulary import LessonCompletionStatus, SignalEventType
from nevo.intelligence.baseline import build_baseline_profile
from nevo.notifications.email import EmailDeliveryUnavailableError, ResendEmailDelivery
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
ArchivedFilter = Annotated[bool, Query(alias="archived")]


class SchoolSummary(BaseModel):
    id: UUID
    name: str
    slug: str | None
    code: str | None


class CurrentUserResponse(BaseModel):
    user_id: UUID
    role: UserRole
    first_name: str | None
    last_name: str | None
    display_name: str
    email: str | None
    school: SchoolSummary | None
    subjects: list[str] = Field(default_factory=list)


def _camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.title() for part in tail)


class ClassStudentResponse(BaseModel):
    model_config = ConfigDict(alias_generator=lambda value: _camel(value), populate_by_name=True)

    student_id: UUID
    first_name: str | None
    last_name: str | None
    display_name: str
    login_identifier: str | None
    status: UserStatus
    profile_status: str = Field(alias="profileStatus")
    latest_session_at: datetime | None = Field(alias="latestSessionAt")
    observations: list[str] = Field(default_factory=list)
    seat_context: str = Field(alias="seatContext")


class ConceptResponse(BaseModel):
    id: UUID
    name: str
    subject: str | None = None


class LessonSegmentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    segment_key: str = Field(alias="segmentKey")
    content_type: LessonContentType = Field(alias="contentType")
    sequence_order: int = Field(alias="sequenceOrder")
    title: str | None
    body: str
    available_modalities: list[str] = Field(alias="availableModalities")
    comprehension_checkpoints: list[dict[str, object]] = Field(alias="comprehensionCheckpoints")
    needs_review: bool = Field(alias="needsReview")
    review_reasons: list[SegmentReviewReason] = Field(alias="reviewReasons")
    estimated_minutes: int = Field(default=0, alias="estimatedMinutes")


class LessonSummaryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    title: str
    source_type: LessonSourceType = Field(alias="sourceType")
    status: ContentParseStatus
    segment_count: int = Field(alias="segmentCount")
    review_segment_count: int = Field(alias="reviewSegmentCount")
    subject: str | None = None
    assignment_count: int = Field(default=0, alias="assignmentCount")
    estimated_minutes: int = Field(default=0, alias="estimatedMinutes")
    created_at: datetime = Field(alias="createdAt")


class LessonDetailResponse(LessonSummaryResponse):
    confirmation_summary: str | None = Field(alias="confirmationSummary")
    segments: list[LessonSegmentResponse]
    modules: list[SharedLessonModuleResponse]


class LessonAssignmentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    lesson_id: UUID = Field(alias="lessonId")
    class_id: UUID | None = Field(default=None, alias="classId")
    student_ids: list[UUID] = Field(default_factory=list, alias="studentIds")
    due_at: datetime | None = Field(default=None, alias="dueAt")
    available_from: datetime | None = Field(default=None, alias="availableFrom")


class LessonAssignmentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    assignment_ids: list[UUID] = Field(alias="assignmentIds")
    created_count: int = Field(alias="createdCount")


class ProfilePatch(BaseModel):
    """Editable fields on the caller's own profile.

    Every field is optional and only applied when present, so a client can send
    just the field the user touched without clearing the others.
    """

    model_config = ConfigDict(populate_by_name=True)

    first_name: str | None = Field(default=None, alias="firstName", max_length=100)
    last_name: str | None = Field(default=None, alias="lastName", max_length=100)
    subjects: list[str] | None = Field(default=None, max_length=50)


class NotificationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    notification_id: UUID = Field(alias="notificationId")
    recipient_id: UUID = Field(alias="recipientId")
    recipient_role: UserRole = Field(alias="recipientRole")
    type: NotificationType
    title: str
    description: str
    read: bool
    created_at: datetime = Field(alias="createdAt")
    navigates_to: str | None = Field(alias="navigatesTo")
    archived: bool = False
    archived_at: datetime | None = Field(default=None, alias="archivedAt")


class NotificationListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    notifications: list[NotificationResponse]
    unread_count: int = Field(alias="unreadCount")
    #: Matching notifications regardless of the page size, so a client can see
    #: that it is looking at a truncated list rather than the whole inbox.
    total: int = 0
    has_more: bool = Field(default=False, alias="hasMore")


class UnreadCountResponse(BaseModel):
    count: int


class MessageThreadResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    thread_id: UUID = Field(alias="threadId")
    recipient_type: MessageRecipientType = Field(alias="recipientType")
    recipient_id: UUID | None = Field(alias="recipientId")
    title: str
    latest_preview: str | None = Field(alias="latestPreview")
    last_message_at: datetime = Field(alias="lastMessageAt")
    class_name: str | None = Field(default=None, alias="className")
    unread: bool
    unread_count: int = Field(alias="unreadCount")


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
    recipient_type: MessageRecipientType = Field(alias="recipientType")
    content: str = Field(min_length=1, max_length=5_000)


class BaselineSubmitRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(alias="sessionId", min_length=1, max_length=120)
    features: list[dict[str, object]] = Field(default_factory=list, max_length=500)


class BaselineSubmitResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: str
    feature_count: int = Field(alias="featureCount")
    baseline_profile: dict[str, object] = Field(alias="baselineProfile")
    engine_config: dict[str, object] = Field(alias="engineConfig")


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
        subjects=await _subjects_for_user(session, user),
    )


@router.patch(
    "/api/v1/users/me",
    response_model=CurrentUserResponse,
    tags=["authentication"],
)
async def update_current_user_profile(
    payload: ProfilePatch,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> CurrentUserResponse:
    """Update the caller's own editable profile fields.

    Name and subjects only. Email is an authentication identifier, so changing
    it needs a verification flow rather than a silent write, and role and
    school are set by an administrator rather than by the account holder.

    ``subjects`` replaces the user's explicitly chosen list. Subjects inferred
    from their lessons are still merged into the response, so the value read
    back can legitimately be a superset of what was written.
    """
    user = await session.get(User, principal.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    changes = payload.model_dump(exclude_unset=True)
    if "first_name" in changes:
        user.first_name = payload.first_name
    if "last_name" in changes:
        user.last_name = payload.last_name
    if "subjects" in changes:
        deduped = list(
            dict.fromkeys(
                subject.strip() for subject in (payload.subjects or []) if subject.strip()
            )
        )
        user.preferences = {**user.preferences, "subjects": deduped}
    await session.commit()
    school = await session.get(School, user.school_id) if user.school_id else None
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
        subjects=await _subjects_for_user(session, user),
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
    if actor.role == UserRole.TEACHER:
        assigned = await session.scalar(
            select(TeacherClassAssignment.id).where(
                TeacherClassAssignment.class_id == class_id,
                TeacherClassAssignment.teacher_id == actor.user_id,
                TeacherClassAssignment.removed_at.is_(None),
            )
        )
        if assigned is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Class not found")
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
    observations = await _student_observations(
        session,
        student_ids=[user.id for user, _, _ in rows],
        school_class=school_class,
    )
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
            observations=observations[user.id]["observations"],
            seatContext=observations[user.id]["seatContext"],
        )
        for user, profile_id, latest_session_at in rows
    ]


async def _student_observations(
    session,
    *,
    student_ids: list[UUID],
    school_class: Class,
) -> dict[UUID, dict[str, object]]:
    if not student_ids:
        return {}
    since = datetime.now(UTC) - timedelta(days=30)
    lesson_sessions = (
        await session.scalars(
            select(LessonSession)
            .where(
                LessonSession.student_id.in_(student_ids),
                LessonSession.started_at >= since,
            )
            .order_by(LessonSession.started_at.desc())
        )
    ).all()
    events = (
        await session.scalars(
            select(SignalEvent).where(
                SignalEvent.student_id.in_(student_ids),
                SignalEvent.timestamp >= since,
                SignalEvent.event_type.in_(
                    (
                        SignalEventType.REPLAY,
                        SignalEventType.SLOWER_TRIGGER,
                        SignalEventType.SIMPLIFY_TRIGGER,
                        SignalEventType.MODALITY_SUGGESTION_ACCEPTED,
                    )
                ),
            )
        )
    ).all()
    sessions_by_student: dict[UUID, list[LessonSession]] = {item: [] for item in student_ids}
    events_by_student: dict[UUID, list[SignalEvent]] = {item: [] for item in student_ids}
    for item in lesson_sessions:
        sessions_by_student[item.student_id].append(item)
    for item in events:
        events_by_student[item.student_id].append(item)
    result: dict[UUID, dict[str, object]] = {}
    class_context = school_class.name
    if school_class.year_group:
        class_context = f"{class_context}, {school_class.year_group}"
    for student_id in student_ids:
        recent_sessions = sessions_by_student[student_id]
        recent_events = events_by_student[student_id]
        completed = sum(
            item.completion_status is LessonCompletionStatus.COMPLETED
            for item in recent_sessions
        )
        replay_count = sum(item.event_type is SignalEventType.REPLAY for item in recent_events)
        pace_changes = sum(
            item.event_type
            in {SignalEventType.SLOWER_TRIGGER, SignalEventType.SIMPLIFY_TRIGGER}
            for item in recent_events
        )
        modality_changes = sum(
            item.event_type is SignalEventType.MODALITY_SUGGESTION_ACCEPTED
            for item in recent_events
        )
        chips: list[str] = []
        if completed:
            chips.append(f"Completed {completed} lesson{'s' if completed != 1 else ''} recently")
        if replay_count >= 3:
            chips.append("Revisited parts of recent lessons")
        if pace_changes:
            chips.append("Used a steadier content pace")
        if modality_changes:
            chips.append("Tried another content format")
        if not chips:
            chips.append("No recent learning pattern to highlight")
        latest_position = next(
            (item.exit_position for item in recent_sessions if item.exit_position),
            None,
        )
        result[student_id] = {
            "observations": chips[:3],
            "seatContext": (
                f"{class_context}, last position {latest_position}"
                if latest_position
                else class_context
            ),
        }
    return result


@router.get("/api/concepts", response_model=list[ConceptResponse], tags=["content"])
async def concepts(
    session: DatabaseSession,
    response: Response,
    ids: str | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1, max_length=120),
    limit: LimitQuery = DEFAULT_LIMIT,
    offset: OffsetQuery = 0,
) -> list[ConceptResponse]:
    """List or look up concepts.

    Totals are in the X-Total-Count and X-Has-More headers. An explicit `ids`
    lookup is not paged — the caller already knows how many it asked for.
    """
    if ids:
        concept_ids = [_uuid(item) for item in ids.split(",") if item.strip()]
        records = (
            await session.scalars(
                select(Concept).where(Concept.id.in_(concept_ids)).order_by(Concept.name)
            )
        ).all()
        set_page_headers(response, total=len(records), limit=len(records) or 1, offset=0)
        return [
            ConceptResponse(id=item.id, name=item.name, subject=item.subject)
            for item in records
        ]
    query = select(Concept).order_by(Concept.name)
    if search:
        query = query.where(Concept.name.ilike(f"%{search}%"))
    records, total = await paginate(session, query, limit=limit, offset=offset)
    set_page_headers(response, total=total, limit=limit, offset=offset)
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
    counts = dict(
        (
            await session.execute(
                select(LessonAssignment.lesson_id, func.count(LessonAssignment.id))
                .where(
                    LessonAssignment.lesson_id.in_([item.id for item in lessons]),
                    LessonAssignment.status != "cancelled",
                )
                .group_by(LessonAssignment.lesson_id)
            )
        ).all()
    )
    return [_lesson_summary(item, assignment_count=int(counts.get(item.id, 0))) for item in lessons]


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
    modules = (
        await session.scalars(
            select(LessonModule)
            .where(LessonModule.lesson_id == lesson_id)
            .order_by(LessonModule.sequence_order)
        )
    ).all()
    assignment_count = await session.scalar(
        select(func.count(LessonAssignment.id)).where(
            LessonAssignment.lesson_id == lesson_id,
            LessonAssignment.status != "cancelled",
        )
    )
    return LessonDetailResponse(
        **_lesson_summary(
            lesson, assignment_count=int(assignment_count or 0)
        ).model_dump(by_alias=True),
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
                estimatedMinutes=item.estimated_minutes,
            )
            for item in segments
        ],
        modules=[
            SharedLessonModuleResponse(
                id=item.id,
                title=item.title,
                recap=item.recap,
                preview=item.preview,
                sequenceOrder=item.sequence_order,
                segmentIds=item.segment_ids,
            )
            for item in modules
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
    if not unique_student_ids:
        return LessonAssignmentResponse(assignmentIds=[], createdCount=0)
    # Idempotent on (lesson, student, availableFrom), matching
    # POST /api/v1/assignments: a retried request must not duplicate rows.
    created = list(
        (
            await session.scalars(
                insert(LessonAssignment)
                .values(
                    [
                        {
                            "lesson_id": payload.lesson_id,
                            "student_id": student_id,
                            "teacher_id": principal.user_id,
                            "class_id": payload.class_id,
                            "assignment_type": "class" if payload.class_id else "student",
                            "due_at": payload.due_at,
                            "available_from": payload.available_from,
                        }
                        for student_id in unique_student_ids
                    ]
                )
                .on_conflict_do_nothing(
                    index_elements=["lesson_id", "student_id", "available_from"],
                )
                .returning(LessonAssignment.id)
            )
        ).all()
    )
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
    archived: ArchivedFilter = False,
    limit: LimitQuery = DEFAULT_LIMIT,
    offset: OffsetQuery = 0,
) -> NotificationListResponse:
    """List the caller's notifications.

    Defaults to the active inbox. Pass ``archived=true`` for the archive view;
    without it, archiving was a one-way action with nowhere to look afterwards.

    ``total`` and ``hasMore`` describe the whole matching set, so a busy inbox
    is visibly paged rather than silently cut off at the page size.
    """
    archived_clause = (
        Notification.archived_at.is_not(None) if archived else Notification.archived_at.is_(None)
    )
    query = (
        select(Notification)
        .where(
            Notification.recipient_id == principal.user_id,
            archived_clause,
        )
        .order_by(Notification.created_at.desc())
    )
    records, total = await paginate(session, query, limit=limit, offset=offset)
    # The badge counts every unread notification in the active inbox, not just
    # the ones on this page — a count that changed as you paged would be wrong.
    unread_total = await session.scalar(
        select(func.count(Notification.id)).where(
            Notification.recipient_id == principal.user_id,
            Notification.archived_at.is_(None),
            Notification.read.is_(False),
        )
    )
    return NotificationListResponse(
        notifications=[_notification(item) for item in records],
        unreadCount=int(unread_total or 0),
        total=total,
        hasMore=has_more(total=total, limit=limit, offset=offset),
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
        .where(Notification.archived_at.is_(None))
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
    query = query.where(_thread_access_clause(user))
    records = (await session.scalars(query.order_by(MessageThread.last_message_at.desc()))).all()
    threads = [await _thread_response(session, item, user.id) for item in records]
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
    await _mark_thread_read(session, thread.id, principal.user_id)
    await session.commit()
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
    "/api/messages/threads/{thread_id}/read",
    response_model=MessageThreadResponse,
    tags=["messaging"],
)
async def mark_thread_read(
    thread_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> MessageThreadResponse:
    """Clear a thread's unread badge without opening it.

    Fetching the thread also marks it read, but that makes clearing the badge
    a side effect of a GET — a prefetch or a retry would clear it. This is the
    explicit way to do it, and returns the updated thread so the badge can be
    reconciled without a second request.
    """
    thread = await _require_thread_access(session, principal.user_id, thread_id)
    await _mark_thread_read(session, thread.id, principal.user_id)
    await session.commit()
    return await _thread_response(session, thread, principal.user_id)


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
    await _mark_thread_read(session, thread.id, user.id)
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
    leaked = {key for feature in features for key in feature if is_private_interaction_key(key)}
    if leaked:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Raw interaction fields are device-only. Submit reduced "
                "aggregate baseline features."
            ),
        )
    baseline_profile, engine_config = build_baseline_profile(
        session_id=payload.session_id,
        features=features,
    )
    await session.execute(
        update(User)
        .where(User.id == principal.user_id)
        .values(
            baseline_profile=baseline_profile,
            engine_config=engine_config,
        )
    )
    await session.commit()
    return BaselineSubmitResponse(
        status="accepted",
        featureCount=len(features),
        baselineProfile=baseline_profile,
        engineConfig=engine_config,
    )


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


@router.get("/api/analytics/schools", response_model=SchoolHealthResponse, tags=["admin"])
async def school_health(actor: OversightScope, session: DatabaseSession) -> dict[str, object]:
    school_id = actor.school_id
    if school_id is None:
        raise HTTPException(status_code=403, detail="School context required")
    student_count = (
        await session.scalar(
            select(func.count(User.id)).where(
                User.school_id == school_id, User.role == UserRole.STUDENT
            )
        )
        or 0
    )
    active_students = (
        await session.scalar(
            select(func.count(func.distinct(LessonSession.student_id)))
            .join(User, User.id == LessonSession.student_id)
            .where(
                User.school_id == school_id,
                LessonSession.started_at >= datetime.now(UTC) - timedelta(days=30),
            )
        )
        or 0
    )
    completed_sessions = (
        await session.scalar(
            select(func.count(LessonSession.id))
            .join(User, User.id == LessonSession.student_id)
            .where(User.school_id == school_id, LessonSession.completion_status == "completed")
        )
        or 0
    )
    return {
        "schoolId": str(school_id),
        "studentCount": int(student_count),
        "activeStudentsLast30Days": int(active_students),
        "completedLessonSessions": int(completed_sessions),
        "participationRate": round(int(active_students) / int(student_count), 4)
        if student_count
        else 0.0,
    }


@router.get("/api/analytics/outcomes", response_model=OutcomesResponse, tags=["admin"])
async def outcomes(
    actor: OversightScope,
    session: DatabaseSession,
    school_id: SchoolIdQuery = None,
) -> dict[str, object]:
    target_school_id = school_id or actor.school_id
    if target_school_id is None or target_school_id != actor.school_id:
        raise HTTPException(status_code=404, detail="School not found")
    rows = (
        await session.execute(
            select(
                func.date_trunc("month", LessonSession.started_at).label("period"),
                func.count(LessonSession.id).label("sessions"),
                func.count(LessonSession.id)
                .filter(LessonSession.completion_status == "completed")
                .label("completed"),
                func.avg(LessonSession.proactive_adjustments_count).label("adaptations"),
            )
            .join(User, User.id == LessonSession.student_id)
            .where(User.school_id == target_school_id)
            .group_by("period")
            .order_by("period")
        )
    ).all()
    return {
        "schoolId": str(target_school_id),
        "outcomes": [
            {
                "period": period.date().isoformat(),
                "sessions": int(sessions),
                "completedSessions": int(completed),
                "completionRate": round(int(completed) / int(sessions), 4) if sessions else 0.0,
                "averageAdaptations": round(float(adaptations or 0), 3),
            }
            for period, sessions, completed, adaptations in rows
        ],
    }


@router.get(
    "/api/intelligence/profile/{student_id}",
    response_model=ProfileAliasResponse,
    tags=["intelligence"],
)
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
        "observedEventCount": profile.observed_event_count,
    }


@router.get(
    "/api/intelligence/flags",
    response_model=list[AttentionFlagResponse],
    tags=["intelligence"],
)
async def flags_alias(
    principal: PrincipalDependency,
    session: DatabaseSession,
    response: Response,
    student_id: StudentIdQuery = None,
    class_id: ClassIdQuery = None,
    limit: LimitQuery = DEFAULT_LIMIT,
    offset: OffsetQuery = 0,
) -> list[dict[str, object]]:
    """List attention flags.

    This returns a bare array, so the unpaged total and whether more remains
    are reported in the X-Total-Count and X-Has-More headers rather than the
    body. Previously the list was capped at 50 with no way to tell.
    """
    actor = await actor_user(session, principal)
    query = select(AttentionFlag).order_by(AttentionFlag.generated_at.desc())
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
    rows, total = await paginate(session, query, limit=limit, offset=offset)
    set_page_headers(response, total=total, limit=limit, offset=offset)
    return [
        {
            "id": str(item.id),
            "studentId": str(item.student_id),
            "flagType": item.flag_type.value,
            "description": item.description,
            "generatedAt": item.generated_at.isoformat(),
            "acknowledged": item.acknowledged_at is not None,
            "evidenceSeries": item.evidence_series,
            "actionTargets": item.action_targets,
        }
        for item in rows
    ]


@router.post(
    "/api/intelligence/flags/{flag_id}/acknowledge",
    response_model=AttentionFlagResponse,
    tags=["intelligence"],
)
async def acknowledge_flag(
    flag_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    """Record that a staff member has seen and actioned a flag.

    Idempotent: acknowledging an already-acknowledged flag keeps the original
    acknowledgement rather than reassigning it to whoever clicked last.
    """
    actor = await actor_user(session, principal)
    if principal.role == "student":
        raise HTTPException(status_code=403, detail="Students cannot acknowledge flags")
    flag = await session.get(AttentionFlag, flag_id)
    if flag is None:
        raise HTTPException(status_code=404, detail="Flag not found")
    await require_student_access(session, principal, flag.student_id)
    if flag.acknowledged_at is None:
        flag.acknowledged_at = datetime.now(UTC)
        flag.acknowledged_by = actor.id
        await session.commit()
    return {
        "id": str(flag.id),
        "studentId": str(flag.student_id),
        "flagType": flag.flag_type.value,
        "description": flag.description,
        "generatedAt": flag.generated_at.isoformat(),
        "acknowledged": True,
        "evidenceSeries": flag.evidence_series,
        "actionTargets": flag.action_targets,
    }


@router.get(
    "/api/intelligence/recommendations/{student_id}",
    response_model=list[InterventionResponse],
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
    request: Request,
) -> ResetReceipt:
    mailer = getattr(request.app.state, "email_delivery", None)
    if not isinstance(mailer, ResendEmailDelivery) or not mailer.configured:
        raise HTTPException(status_code=503, detail="Password reset email is unavailable")
    user = await session.scalar(select(User).where(func.lower(User.email) == payload.email.lower()))
    if user is not None:
        token = secrets.token_urlsafe(32)
        session.add(
            PasswordResetToken(
                user_id=user.id,
                token_digest=hashlib.sha256(token.encode()).hexdigest(),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        await session.commit()
        try:
            await mailer.send(
                to=str(user.email),
                subject="Reset your Nevo password",
                text=(
                    "A password reset was requested for your Nevo account.\n\n"
                    f"Reset it here: {mailer.frontend_base_url}/reset-password?token={token}\n\n"
                    "This link expires in one hour. If you did not request it, "
                    "you can ignore this email."
                ),
            )
        except EmailDeliveryUnavailableError as error:
            raise HTTPException(
                status_code=503, detail="Password reset email is unavailable"
            ) from error
    return ResetReceipt(
        status="accepted",
        message="If the account exists, Nevo will send password reset instructions.",
    )


@router.get(
    "/api/settings/me",
    response_model=SettingsResponse,
    tags=["school administration"],
)
async def get_settings(
    principal: PrincipalDependency, session: DatabaseSession
) -> SettingsResponse:
    user = await actor_user(session, principal)
    return SettingsResponse(
        settings={"userId": str(user.id), "preferences": dict(user.preferences)}
    )


@router.put(
    "/api/settings/me",
    response_model=SettingsResponse,
    tags=["school administration"],
)
async def update_settings(
    payload: UpdateSettingsRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> SettingsResponse:
    user = await actor_user(session, principal)
    user.preferences = {**dict(user.preferences), **(payload.model_extra or {})}
    await session.commit()
    return SettingsResponse(settings={"userId": str(user.id), "preferences": user.preferences})


def _display_name(user: User) -> str:
    name = " ".join(part for part in (user.first_name, user.last_name) if part)
    return name or user.email or user.login_identifier or "Nevo user"


async def _subjects_for_user(session, user: User) -> list[str]:
    subjects = {
        str(item).strip()
        for item in user.preferences.get("subjects", [])
        if str(item).strip()
    }
    query = select(Lesson.subject).where(Lesson.subject.is_not(None))
    if user.role is UserRole.STUDENT:
        query = query.join(
            LessonAssignment,
            LessonAssignment.lesson_id == Lesson.id,
        ).where(
            LessonAssignment.student_id == user.id,
            LessonAssignment.status != "cancelled",
        )
    elif user.role is UserRole.TEACHER:
        query = query.where(Lesson.created_by_user_id == user.id)
    elif user.school_id is not None:
        query = query.where(Lesson.school_id == user.school_id)
    else:
        return sorted(subjects, key=str.casefold)
    subjects.update(
        str(item).strip()
        for item in (await session.scalars(query.distinct())).all()
        if item and str(item).strip()
    )
    return sorted(subjects, key=str.casefold)


def _uuid(value: str) -> UUID:
    try:
        return UUID(value.strip())
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid concept id",
        ) from error


def _lesson_summary(lesson: Lesson, *, assignment_count: int = 0) -> LessonSummaryResponse:
    return LessonSummaryResponse(
        id=lesson.id,
        title=lesson.title,
        sourceType=lesson.source_type.value,
        status=lesson.status.value,
        segmentCount=lesson.segment_count,
        reviewSegmentCount=lesson.review_segment_count,
        subject=lesson.subject,
        assignmentCount=assignment_count,
        estimatedMinutes=lesson.estimated_minutes,
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
        archived=item.archived_at is not None,
        archivedAt=item.archived_at,
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


async def _thread_response(
    session, thread: MessageThread, viewer_id: UUID
) -> MessageThreadResponse:
    title = "Conversation"
    recipient_id = None
    class_name = None
    if thread.recipient_type == "student" and thread.student_id:
        student = await session.get(User, thread.student_id)
        title = _display_name(student) if student else "Student conversation"
        recipient_id = thread.student_id
    elif thread.recipient_type == "class" and thread.class_id:
        school_class = await session.get(Class, thread.class_id)
        title = school_class.name if school_class else "Class conversation"
        class_name = school_class.name if school_class else None
        recipient_id = thread.class_id
    last_read_at = await session.scalar(
        select(MessageThreadRead.last_read_at).where(
            MessageThreadRead.thread_id == thread.id,
            MessageThreadRead.user_id == viewer_id,
        )
    )
    unread_count = await session.scalar(
        select(func.count(Message.id)).where(
            Message.thread_id == thread.id,
            Message.sender_id != viewer_id,
            Message.created_at > (last_read_at or datetime.min.replace(tzinfo=UTC)),
        )
    )
    return MessageThreadResponse(
        threadId=thread.id,
        recipientType=thread.recipient_type,
        recipientId=recipient_id,
        title=title,
        latestPreview=thread.latest_preview,
        lastMessageAt=thread.last_message_at,
        className=class_name,
        unread=bool(unread_count),
        unreadCount=int(unread_count or 0),
    )


async def _mark_thread_read(session, thread_id: UUID, user_id: UUID) -> None:
    record = await session.scalar(
        select(MessageThreadRead).where(
            MessageThreadRead.thread_id == thread_id,
            MessageThreadRead.user_id == user_id,
        )
    )
    if record is None:
        session.add(
            MessageThreadRead(
                thread_id=thread_id,
                user_id=user_id,
                last_read_at=datetime.now(UTC),
            )
        )
    else:
        record.last_read_at = datetime.now(UTC)


async def _require_thread_access(session, user_id: UUID, thread_id: UUID) -> MessageThread:
    user = await session.get(User, user_id)
    thread = await session.get(MessageThread, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    if user is None or user.school_id != thread.school_id:
        raise HTTPException(status_code=403, detail="Thread is outside your school")
    allowed = await session.scalar(
        select(MessageThread.id).where(
            MessageThread.id == thread.id,
            _thread_access_clause(user),
        )
    )
    if allowed is None:
        raise HTTPException(status_code=403, detail="Thread is not available to this account")
    return thread


async def _find_or_create_thread(
    session,
    user: User,
    payload: SendMessageRequest,
) -> MessageThread:
    if user.role == UserRole.STUDENT:
        if payload.recipient_type != "student" or payload.recipient_id != user.id:
            raise HTTPException(status_code=403, detail="Students can message only in their thread")
    elif user.role == UserRole.PARENT_GUARDIAN:
        linked = await session.scalar(
            select(ParentLink.id).where(
                ParentLink.parent_id == user.id,
                ParentLink.student_id == payload.recipient_id,
            )
        )
        if payload.recipient_type != "student" or linked is None:
            raise HTTPException(status_code=403, detail="Student is not linked to this account")
    elif user.role == UserRole.TEACHER:
        if payload.recipient_type == "student":
            if not await can_access_student(session, user, payload.recipient_id):
                raise HTTPException(status_code=404, detail="Student not found")
        else:
            await require_class_access(session, user, payload.recipient_id)
    elif user.role not in {UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}:
        raise HTTPException(status_code=403, detail="Messaging is not available to this account")
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


def _thread_access_clause(user: User):
    if user.role in {UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}:
        return MessageThread.school_id == user.school_id
    if user.role == UserRole.STUDENT:
        enrolled_classes = select(StudentClassEnrollment.class_id).where(
            StudentClassEnrollment.student_id == user.id
        )
        return or_(
            MessageThread.student_id == user.id,
            MessageThread.class_id.in_(enrolled_classes),
        )
    if user.role == UserRole.TEACHER:
        assigned_classes = select(TeacherClassAssignment.class_id).where(
            TeacherClassAssignment.teacher_id == user.id,
            TeacherClassAssignment.removed_at.is_(None),
        )
        assigned_students = select(StudentClassEnrollment.student_id).where(
            StudentClassEnrollment.class_id.in_(assigned_classes)
        )
        return or_(
            MessageThread.created_by_id == user.id,
            MessageThread.class_id.in_(assigned_classes),
            MessageThread.student_id.in_(assigned_students),
        )
    if user.role == UserRole.PARENT_GUARDIAN:
        linked_students = select(ParentLink.student_id).where(ParentLink.parent_id == user.id)
        return MessageThread.student_id.in_(linked_students)
    return MessageThread.id.is_(None)
