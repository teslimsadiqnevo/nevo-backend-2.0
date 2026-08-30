"""Complete the design-backed product contracts.

Revision ID: 20260829_0029
Revises: 20260828_0028
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260829_0029"
down_revision: str | Sequence[str] | None = "20260828_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> postgresql.UUID:
    return postgresql.UUID(as_uuid=True)


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def upgrade() -> None:
    json_object = sa.text("'{}'::jsonb")
    json_array = sa.text("'[]'::jsonb")
    op.add_column(
        "schools",
        sa.Column("profile", postgresql.JSONB(), server_default=json_object, nullable=False),
    )
    op.add_column(
        "schools",
        sa.Column(
            "academic_config", postgresql.JSONB(), server_default=json_object, nullable=False
        ),
    )
    op.add_column(
        "schools",
        sa.Column("retention_policy", sa.String(40), server_default="contract", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("engine_config", postgresql.JSONB(), server_default=json_object, nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("preferences", postgresql.JSONB(), server_default=json_object, nullable=False),
    )
    op.add_column("users", sa.Column("age_band", sa.String(40), nullable=True))
    op.add_column("classes", sa.Column("year_group", sa.String(20), nullable=True))
    op.add_column(
        "classes", sa.Column("source", sa.String(20), server_default="manual", nullable=False)
    )
    op.add_column("classes", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "notifications",
        sa.Column("category", sa.String(80), server_default="general", nullable=False),
    )
    op.add_column(
        "notifications", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_table(
        "school_invitations",
        sa.Column("id", _uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "school_id", _uuid(), sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column("first_name", sa.String(100)),
        sa.Column("last_name", sa.String(100)),
        sa.Column("email", sa.String(255)),
        sa.Column("parent_contact", sa.String(255)),
        sa.Column("class_id", _uuid(), sa.ForeignKey("classes.id", ondelete="SET NULL")),
        sa.Column("token_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_by_id", _uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_school_invitations_school_status", "school_invitations", ["school_id", "status"]
    )
    op.create_index(
        "ix_school_invitations_token", "school_invitations", ["token_digest"], unique=True
    )

    op.create_table(
        "parent_data_requests",
        sa.Column("id", _uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "student_id", _uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "parent_id", _uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("request_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(32), server_default="open", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_parent_data_requests_student_status", "parent_data_requests", ["student_id", "status"]
    )

    op.create_table(
        "student_enrollment_history",
        sa.Column("id", _uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "student_id", _uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("from_class_id", _uuid()),
        sa.Column("to_class_id", _uuid()),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("actor_user_id", _uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("details", postgresql.JSONB(), server_default=json_object, nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_student_enrollment_history_student",
        "student_enrollment_history",
        ["student_id", "occurred_at"],
    )

    op.create_table(
        "lesson_modules",
        sa.Column("id", _uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "lesson_id", _uuid(), sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("recap", sa.Text()),
        sa.Column("preview", sa.Text()),
        sa.Column("sequence_order", sa.Integer(), nullable=False),
        sa.Column("segment_ids", postgresql.JSONB(), server_default=json_array, nullable=False),
        sa.UniqueConstraint("lesson_id", "sequence_order", name="uq_lesson_modules_order"),
    )
    op.create_index("ix_lesson_modules_lesson", "lesson_modules", ["lesson_id", "sequence_order"])

    op.create_table(
        "upload_jobs",
        sa.Column("id", _uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "school_id", _uuid(), sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "requested_by_id",
            _uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("stage", sa.String(32), server_default="lessons", nullable=False),
        sa.Column("structure", postgresql.JSONB(), server_default=json_object, nullable=False),
        sa.Column("undo_stack", postgresql.JSONB(), server_default=json_array, nullable=False),
        sa.Column("error_message", sa.Text()),
        *_timestamps(),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_upload_jobs_requester_status", "upload_jobs", ["requested_by_id", "status"])

    op.create_table(
        "lesson_progress",
        sa.Column("id", _uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "student_id", _uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "lesson_id", _uuid(), sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "assignment_id", _uuid(), sa.ForeignKey("lesson_assignments.id", ondelete="SET NULL")
        ),
        sa.Column("session_id", _uuid()),
        sa.Column("module_position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("segment_position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(32), server_default="not_started", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("student_id", "lesson_id", name="uq_lesson_progress_student_lesson"),
    )
    op.create_index(
        "ix_lesson_progress_student_updated", "lesson_progress", ["student_id", "updated_at"]
    )

    op.create_table(
        "user_connections",
        sa.Column("id", _uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("school_id", _uuid(), nullable=False),
        sa.Column(
            "student_id", _uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "teacher_id", _uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("class_id", _uuid()),
        sa.Column("status", sa.String(24), server_default="pending", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("responded_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("student_id", "teacher_id", name="uq_user_connections_pair"),
    )
    op.create_index(
        "ix_user_connections_teacher_status", "user_connections", ["teacher_id", "status"]
    )

    op.create_table(
        "offline_downloads",
        sa.Column("id", _uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "student_id", _uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "lesson_id", _uuid(), sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("manifest", postgresql.JSONB(), server_default=json_object, nullable=False),
        sa.Column(
            "downloaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("student_id", "lesson_id", name="uq_offline_download_student_lesson"),
    )

    op.create_table(
        "feedback_submissions",
        sa.Column("id", _uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("account_ref", sa.String(64), nullable=False),
        sa.Column("school_id", _uuid()),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column("feedback_type", sa.String(40), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("context", sa.String(120), nullable=False),
        sa.Column("status", sa.String(24), server_default="new", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_feedback_submissions_created", "feedback_submissions", ["created_at"])

    op.create_table(
        "notification_preferences",
        sa.Column("id", _uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "user_id", _uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("in_app", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("email", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.UniqueConstraint(
            "user_id", "category", name="uq_notification_preferences_user_category"
        ),
    )
    op.create_table(
        "post_lesson_processing",
        sa.Column("session_id", _uuid(), primary_key=True),
        sa.Column(
            "student_id",
            _uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    for table in (
        "post_lesson_processing",
        "notification_preferences",
        "feedback_submissions",
        "offline_downloads",
        "user_connections",
        "lesson_progress",
        "upload_jobs",
        "lesson_modules",
        "student_enrollment_history",
        "parent_data_requests",
        "school_invitations",
    ):
        op.drop_table(table)
    op.drop_column("notifications", "archived_at")
    op.drop_column("notifications", "category")
    op.drop_column("classes", "archived_at")
    op.drop_column("classes", "source")
    op.drop_column("classes", "year_group")
    op.drop_column("users", "age_band")
    op.drop_column("users", "preferences")
    op.drop_column("users", "engine_config")
    op.drop_column("schools", "retention_policy")
    op.drop_column("schools", "academic_config")
    op.drop_column("schools", "profile")
