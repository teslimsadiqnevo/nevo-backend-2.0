from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from nevo.domain.accounts.vocabulary import (
    AuthMethod,
    ClassSource,
    InvitationDeliveryStatus,
    NotificationCategory,
    UserRole,
    UserStatus,
)
from nevo.domain.attention_flags.vocabulary import AttentionFlagType
from nevo.domain.intelligence.vocabulary import (
    AssignmentStatus,
    ContentParseStatus,
    LessonContentType,
    LessonSourceType,
    SegmentReviewReason,
    UploadStage,
    UploadStatus,
)
from nevo.domain.signal_events.vocabulary import LessonCompletionStatus


def _camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.title() for part in tail)


class CamelResponse(BaseModel):
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True)


class SchoolResponse(CamelResponse):
    id: UUID
    name: str
    code: str | None
    slug: str | None
    profile: dict[str, object]
    academic_config: dict[str, object]
    retention_policy: str
    retention_days: int


class SchoolOverviewResponse(CamelResponse):
    school_id: UUID
    counts: dict[str, int]


class ClassSummaryResponse(CamelResponse):
    id: UUID
    name: str
    code: str | None
    year_group: str | None
    source: ClassSource | None = None
    subjects: list[str] = Field(default_factory=list)
    student_count: int
    archived_at: datetime | None


class ClassOptionResponse(CamelResponse):
    id: UUID
    name: str
    year_group: str | None


class IdCodeResponse(CamelResponse):
    id: UUID
    code: str | None


class IdNameResponse(CamelResponse):
    id: UUID
    name: str


class TeacherSummaryResponse(CamelResponse):
    id: UUID
    name: str
    email: str | None
    status: UserStatus


class TeacherDetailResponse(TeacherSummaryResponse):
    class_ids: list[UUID]


class StudentSummaryResponse(CamelResponse):
    id: UUID
    name: str
    login_identifier: str | None
    status: UserStatus
    age_band: str | None


class StudentDetailResponse(CamelResponse):
    id: UUID
    first_name: str | None
    last_name: str | None
    login_identifier: str | None
    email: str | None
    status: UserStatus
    age_band: str | None
    class_ids: list[UUID]
    first_use: bool


class StudentEnrollmentResponse(CamelResponse):
    id: UUID
    login_identifier: str


class StudentMoveResponse(CamelResponse):
    student_id: UUID
    class_id: UUID


class PinIssueResponse(CamelResponse):
    student_id: UUID
    pin: str
    issued_at: datetime
    must_share_securely: bool


class NotificationPreferenceResponse(CamelResponse):
    category: NotificationCategory
    in_app: bool
    email: bool


class PersonalSettingsResponse(CamelResponse):
    user_id: UUID
    preferences: dict[str, object]


class OpsFeedbackResponse(CamelResponse):
    id: UUID
    account_ref: str
    role: UserRole
    type: str
    note: str
    context: str
    status: str
    created_at: datetime


class OpsOverviewResponse(CamelResponse):
    schools: int
    active_users: int
    lesson_sessions: int
    raw_touch_signals_exposed: Literal[0]


class SchoolCodeResponse(CamelResponse):
    school_id: UUID
    school_name: str
    auth_method: AuthMethod
    classes: list[ClassOptionResponse]


class AuthSessionRecordResponse(CamelResponse):
    id: UUID
    current: bool
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    active: bool


class InvitationResponse(CamelResponse):
    id: UUID
    token: str | None = None
    role: str | None = None
    email: str | None = None
    name: str | None = None
    status: str | None = None
    expires_at: datetime
    delivery_status: InvitationDeliveryStatus | None = None


class RejectedInvitationResponse(CamelResponse):
    row: int
    reason: str


class BulkInvitationResponse(CamelResponse):
    created: list[InvitationResponse]
    rejected: list[RejectedInvitationResponse]


class JoinInspectionResponse(CamelResponse):
    status: Literal["valid"]
    role: UserRole
    school_name: str | None
    expires_at: datetime


class JoinAcceptedResponse(CamelResponse):
    user_id: UUID
    role: UserRole
    login_identifier: str | None


class ParentRightResponse(CamelResponse):
    request_id: UUID
    status: str


class LessonSummaryResponse(CamelResponse):
    id: UUID
    title: str
    status: ContentParseStatus
    source_type: LessonSourceType
    segment_count: int
    review_segment_count: int
    subject: str | None = None
    assignment_count: int = 0
    #: Sum of the lesson's segment estimates, so a list view can show a
    #: duration without fetching every segment.
    estimated_minutes: int = 0
    created_at: datetime


class LessonSegmentResponse(CamelResponse):
    id: UUID
    segment_key: str
    sequence_order: int
    content_type: LessonContentType
    title: str | None
    body: str
    available_modalities: list[str]
    comprehension_checkpoints: list[dict[str, object]]
    needs_review: bool = False
    review_reasons: list[SegmentReviewReason] = Field(default_factory=list)
    #: Estimated time to work through this segment, for the review screen's
    #: per-segment and total minute figures.
    estimated_minutes: int = 0


class LessonModuleResponse(CamelResponse):
    id: UUID
    title: str
    recap: str | None
    preview: str | None
    sequence_order: int
    segment_ids: list[str]


class LessonDetailResponse(LessonSummaryResponse):
    confirmation_summary: str | None
    segments: list[LessonSegmentResponse]
    modules: list[LessonModuleResponse]


class AssignmentResponse(CamelResponse):
    id: UUID
    lesson: LessonSummaryResponse
    student_id: UUID
    class_id: UUID | None
    status: AssignmentStatus
    due_at: datetime | None
    available_from: datetime | None
    assigned_at: datetime


class AssignmentCreatedResponse(CamelResponse):
    assignment_ids: list[UUID]
    created_count: int
    #: Rows the request re-sent that already existed. A retry of a partially
    #: failed fan-out reports 0 created and N duplicate, rather than erroring.
    duplicate_count: int = 0


class AssignmentUpdatedResponse(CamelResponse):
    id: UUID
    status: AssignmentStatus
    due_at: datetime | None
    available_from: datetime | None


class LessonSessionResponse(CamelResponse):
    session_id: UUID
    resumed: bool


class LessonProgressResponse(CamelResponse):
    lesson_id: UUID
    status: LessonCompletionStatus
    module_position: int
    segment_position: int
    intelligence: dict[str, object]


class PersonReferenceResponse(CamelResponse):
    id: UUID
    first_name: str | None
    last_name: str | None = None
    age_band: str | None = None


class RecentProgressResponse(CamelResponse):
    lesson_id: UUID
    status: LessonCompletionStatus
    segment_position: int
    updated_at: datetime


class StudentDashboardResponse(CamelResponse):
    student: PersonReferenceResponse
    assignments: list[AssignmentResponse]
    recent_progress: list[RecentProgressResponse]


class LearnerProfileSummaryResponse(CamelResponse):
    version: int
    observed_event_count: int
    last_evaluated_at: datetime | None


class StudentProfileResponse(CamelResponse):
    student: PersonReferenceResponse
    profile: LearnerProfileSummaryResponse | None
    open_flag_count: int


class TeacherDashboardResponse(CamelResponse):
    teacher: PersonReferenceResponse
    classes: list[ClassOptionResponse]


class ClassLearningPulseResponse(CamelResponse):
    class_id: UUID
    class_name: str
    student_count: int
    engagement: float | None
    comprehension: float | None
    focus: float | None


class TeacherRecentActivityResponse(CamelResponse):
    id: str
    activity_type: str
    occurred_at: datetime
    title: str
    detail: str
    class_id: UUID | None = None
    student_id: UUID | None = None
    lesson_id: UUID | None = None
    action_target: str


class TeacherHomeResponse(CamelResponse):
    class_learning_pulse: list[ClassLearningPulseResponse]
    recent_activity: list[TeacherRecentActivityResponse]


class SegmentCompletionResponse(CamelResponse):
    segment_id: UUID
    segment_key: str
    title: str | None
    sequence_order: int
    assigned_student_count: int
    completion_count: int
    completion_rate: float
    average_time_seconds: float | None
    slowdown_count: int
    note: str | None


class LessonClassProgressResponse(CamelResponse):
    lesson_id: UUID
    class_id: UUID
    assigned_student_count: int
    segments: list[SegmentCompletionResponse]
    slowest_segment_id: UUID | None
    slowdown_note: str | None


class ConnectionResponse(CamelResponse):
    class_id: UUID
    status: str


class OfflineManifestResponse(CamelResponse):
    lesson_id: UUID
    version: int
    segment_count: int
    generated_at: datetime
    package_url: str


class OfflineDownloadResponse(CamelResponse):
    id: UUID
    manifest: OfflineManifestResponse


class UploadCreatedResponse(CamelResponse):
    upload_id: UUID
    status: UploadStatus
    stage: UploadStage


class BatchUploadItemResponse(CamelResponse):
    """One file's outcome inside a batch upload."""

    filename: str
    accepted: bool
    upload_id: UUID | None = None
    status: UploadStatus | None = None
    stage: UploadStage | None = None
    #: Why this file was not accepted. Populated only when accepted is false.
    error: str | None = None


class BatchUploadResponse(CamelResponse):
    """Result of submitting several files at once.

    One bad file does not fail the batch: each file reports its own outcome so
    the picker can show which landed and which need attention.
    """

    uploads: list[BatchUploadItemResponse]
    accepted_count: int
    rejected_count: int


class UploadStatusResponse(CamelResponse):
    id: UUID
    status: UploadStatus
    stage: UploadStage
    structure: "UploadStructureDocument"
    error: str | None


class UploadModuleDocument(CamelResponse):
    title: str
    sequence_order: int
    segment_ids: list[str]
    recap: str | None = None
    preview: str | None = None


class UploadLessonDocument(CamelResponse):
    """One lesson produced by an upload.

    A unit or term scope can legitimately parse into several lessons; this is
    the unit that carries its own modules.
    """

    lesson_id: UUID
    title: str
    sequence_order: int
    modules: list[UploadModuleDocument] = Field(default_factory=list)


class UploadStructureDocument(CamelResponse):
    #: The full set of lessons this upload produced. A `lesson` scope yields
    #: one; a `unit` or `term` scope can yield several.
    lessons: list[UploadLessonDocument] = Field(default_factory=list)
    #: First lesson's id. Retained so existing single-lesson clients keep
    #: working; prefer `lessons` for anything that can produce more than one.
    lesson_id: UUID
    #: First lesson's modules, retained for the same reason.
    modules: list[UploadModuleDocument]
    review_notes: list[dict[str, object]] = Field(default_factory=list)


class UploadStructureResponse(CamelResponse):
    id: UUID
    structure: UploadStructureDocument
    can_undo: bool | None = None


class UploadConfirmedResponse(CamelResponse):
    lesson_id: UUID
    status: str


class UploadRetryResponse(CamelResponse):
    upload_id: UUID
    lesson_id: UUID
    pages_retried: list[int]
    structure: UploadStructureDocument


class AttentionFlagResponse(CamelResponse):
    id: UUID
    student_id: UUID
    flag_type: AttentionFlagType
    description: str
    generated_at: datetime
    acknowledged: bool
    evidence_series: list[float] = Field(default_factory=list)
    action_targets: list[str] = Field(default_factory=list)


class InterventionResponse(CamelResponse):
    id: UUID
    student_id: UUID
    recommendation_text: str
    generated_at: datetime


class ProfileAliasResponse(CamelResponse):
    student_id: UUID
    status: Literal["observed", "not_observed_yet"]
    observed_event_count: int | None = None


class SchoolHealthResponse(CamelResponse):
    school_id: UUID
    student_count: int
    active_students_last30_days: int = Field(alias="activeStudentsLast30Days")
    completed_lesson_sessions: int
    participation_rate: float


class OutcomePeriodResponse(CamelResponse):
    period: date
    sessions: int
    completed_sessions: int
    completion_rate: float
    average_adaptations: float


class OutcomesResponse(CamelResponse):
    school_id: UUID
    outcomes: list[OutcomePeriodResponse]


class EngineConfigResponse(CamelResponse):
    student_id: UUID
    configured: bool
    engine_config: dict[str, object]
    baseline_version: int | None


class AdaptationResponse(CamelResponse):
    id: UUID
    student_id: UUID
    lesson_id: UUID
    lesson_title: str
    timestamp: datetime
    event_type: str
    trigger: str
    adaptation: str
    suppressed: bool


class ConversationEvidenceResponse(CamelResponse):
    student_id: UUID
    period_days: int
    interaction_count: int
    categories: dict[str, int]
    helpful_response_rate: float | None
    privacy: Literal["aggregate_only", "withheld_below_minimum"]
    minimum_interactions: int = 3


class MisconceptionResponse(CamelResponse):
    concept_id: UUID
    concept_name: str
    pattern: str
    student_count: int
    description: str


class TransformationMetricsResponse(CamelResponse):
    scope: Literal["student", "cohort", "school"]
    student_count: int
    lessons_transformed: int
    transformation_runs: int
    lesson_sessions: int
    adaptations_applied: int
    adaptations_per_session: float


class ConceptProgressResponse(CamelResponse):
    concept_id: UUID
    name: str
    subject: str | None
    understanding: float
    reading: float
    practice_count: int


class LessonProgressItemResponse(CamelResponse):
    lesson_id: UUID
    title: str
    status: str
    module_position: int
    segment_position: int
    position_base: Literal[0] = 0
    module_number: int
    segment_number: int
    updated_at: datetime


class StudentProgressResponse(CamelResponse):
    student_id: UUID
    subject: str | None
    mastery_average: float | None
    concepts: list[ConceptProgressResponse]
    lessons: list[LessonProgressItemResponse]
