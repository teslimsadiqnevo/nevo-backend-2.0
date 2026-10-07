import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base


class SchoolInvitation(Base):
    __tablename__ = "school_invitations"
    __table_args__ = (
        Index("ix_school_invitations_school_status", "school_id", "status"),
        Index("ix_school_invitations_token", "token_digest", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_contact: Mapped[str | None] = mapped_column(String(255), nullable=True)
    consent_request_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="not_sent", server_default="not_sent"
    )
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("classes.id", ondelete="SET NULL"), nullable=True
    )
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DpaAcceptance(Base):
    __tablename__ = "dpa_acceptances"
    __table_args__ = (
        UniqueConstraint("school_id", "version", name="uq_dpa_acceptances_school_version"),
        Index("ix_dpa_acceptances_school_accepted", "school_id", "accepted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    accepted_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StudentOnboardingGrant(Base):
    """One-use proof that a pre-auth student supplied a valid class code."""

    __tablename__ = "student_onboarding_grants"
    __table_args__ = (
        Index("uq_student_onboarding_grants_token", "token_digest", unique=True),
        Index("ix_student_onboarding_grants_expiry", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("classes.id", ondelete="CASCADE"), nullable=False
    )
    #: Which child this link is for. The link used to name only a class, so
    #: the child had to type their own name and age into it; with the roster
    #: as the source, the link resolves to a person instead.
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ParentDataRequest(Base):
    __tablename__ = "parent_data_requests"
    __table_args__ = (Index("ix_parent_data_requests_student_status", "student_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    parent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    request_type: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="open", server_default="open"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EnrollmentHistory(Base):
    __tablename__ = "student_enrollment_history"
    __table_args__ = (Index("ix_student_enrollment_history_student", "student_id", "occurred_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    from_class_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    to_class_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    details: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LessonModule(Base):
    __tablename__ = "lesson_modules"
    __table_args__ = (
        UniqueConstraint("lesson_id", "sequence_order", name="uq_lesson_modules_order"),
        Index("ix_lesson_modules_lesson", "lesson_id", "sequence_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    recap: Mapped[str | None] = mapped_column(Text)
    preview: Mapped[str | None] = mapped_column(Text)
    sequence_order: Mapped[int] = mapped_column(Integer, nullable=False)
    segment_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )


class UploadJob(Base):
    __tablename__ = "upload_jobs"
    __table_args__ = (Index("ix_upload_jobs_requester_status", "requested_by_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    requested_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    stage: Mapped[str] = mapped_column(
        String(32), nullable=False, default="lessons", server_default="lessons"
    )
    structure: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    undo_stack: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    #: Raw, for us: whatever the driver or the provider said. Never prose and
    #: never to be shown to a teacher.
    error_message: Mapped[str | None] = mapped_column(Text)
    #: A sentence a teacher can act on. The channel ``error_message`` was
    #: wrongly used as, kept apart from it so each can stay what it is.
    failure_reason: Mapped[str | None] = mapped_column(Text)
    #: The same 12 hex characters an unhandled 500 carries. A parse fails
    #: behind the response, so there is no 500 for it to ride on.
    incident_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UploadSourceBlob(Base):
    __tablename__ = "upload_source_blobs"

    upload_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("upload_jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LessonProgress(Base):
    __tablename__ = "lesson_progress"
    __table_args__ = (
        UniqueConstraint("student_id", "lesson_id", name="uq_lesson_progress_student_lesson"),
        CheckConstraint(
            "check_position IS NULL OR check_position >= 0",
            name="ck_lesson_progress_check_position_non_negative",
        ),
        Index("ix_lesson_progress_student_updated", "student_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
    )
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("lesson_assignments.id", ondelete="SET NULL"), nullable=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    module_position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    segment_position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    check_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    check_resumable_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="not_started", server_default="not_started"
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class LessonQuestionAttempt(Base):
    """One submitted answer, preserved exactly as the learner saw it."""

    __tablename__ = "lesson_question_attempts"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "question_id",
            "attempt_number",
            name="uq_lesson_question_attempt_session_question_number",
        ),
        UniqueConstraint("client_attempt_id", name="uq_lesson_question_attempt_client_id"),
        Index(
            "ix_lesson_question_attempts_student_lesson_submitted",
            "student_id",
            "lesson_id",
            "submitted_at",
        ),
        CheckConstraint("attempt_number >= 1", name="lesson_question_attempt_number_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("lesson_sessions.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[str] = mapped_column(String(160), nullable=False)
    segment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("lesson_segments.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    client_attempt_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    question_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    answer: Mapped[object] = mapped_column(JSONB, nullable=False)
    correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UserConnection(Base):
    __tablename__ = "user_connections"
    __table_args__ = (
        UniqueConstraint("student_id", "teacher_id", name="uq_user_connections_pair"),
        Index("ix_user_connections_teacher_status", "teacher_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    school_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    class_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OfflineDownload(Base):
    __tablename__ = "offline_downloads"
    __table_args__ = (
        UniqueConstraint("student_id", "lesson_id", name="uq_offline_download_student_lesson"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
    )
    manifest: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    downloaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class FeedbackSubmission(Base):
    __tablename__ = "feedback_submissions"
    __table_args__ = (Index("ix_feedback_submissions_created", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    account_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    school_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    feedback_type: Mapped[str] = mapped_column(String(40), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="new", server_default="new"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "category", name="uq_notification_preferences_user_category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    in_app: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    email: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )


class SharedDeviceProfile(Base):
    """One locally cached sign-in tile on a shared classroom device."""

    __tablename__ = "shared_device_profiles"
    __table_args__ = (
        UniqueConstraint(
            "device_id", "student_id", name="uq_shared_device_profiles_device_student"
        ),
        UniqueConstraint(
            "device_id",
            "avatar_shape",
            "avatar_colourway",
            name="uq_shared_device_profiles_device_avatar",
        ),
        Index("ix_shared_device_profiles_school_device", "school_id", "device_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    device_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    avatar_shape: Mapped[str] = mapped_column(String(24), nullable=False)
    avatar_colourway: Mapped[str] = mapped_column(String(24), nullable=False)
    provisioned_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PostLessonProcessing(Base):
    __tablename__ = "post_lesson_processing"
    __table_args__ = (Index("ix_post_lesson_processing_due", "status", "next_attempt_at"),)

    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending", server_default="pending"
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    profile_updated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    flags_evaluated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
