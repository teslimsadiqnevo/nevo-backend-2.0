"""Add frontend unblocker support tables.

Revision ID: 20260828_0028
Revises: 20260824_0027
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260828_0028"
down_revision: str | Sequence[str] | None = "20260824_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "baseline_profile",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )

    op.create_table(
        "concepts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=120), nullable=True),
        sa.Column("source", sa.String(length=80), server_default="manual", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_concepts_school_name", "concepts", ["school_id", "name"])
    op.create_index("ix_concepts_subject_name", "concepts", ["subject", "name"])

    op.create_table(
        "notifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_role", sa.String(length=80), nullable=False),
        sa.Column("type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("navigates_to", sa.String(length=255), nullable=True),
        sa.Column("read", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["recipient_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notifications_recipient_created", "notifications", ["recipient_id", "created_at"])
    op.create_index(
        "ix_notifications_recipient_unread",
        "notifications",
        ["recipient_id", "read"],
        postgresql_where=sa.text("read = false"),
    )

    op.create_table(
        "message_threads",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_type", sa.String(length=40), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("class_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("latest_preview", sa.String(length=255), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_message_threads_school_last", "message_threads", ["school_id", "last_message_at"])
    op.create_index("ix_message_threads_student_last", "message_threads", ["student_id", "last_message_at"])

    op.create_table(
        "messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sender_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["thread_id"], ["message_threads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_thread_created", "messages", ["thread_id", "created_at"])

    op.create_table(
        "lesson_assignments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("lesson_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("teacher_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("class_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assignment_type", sa.String(length=40), server_default="class", nullable=False),
        sa.Column("status", sa.String(length=40), server_default="assigned", nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lesson_assignments_student_status", "lesson_assignments", ["student_id", "status"])
    op.create_index("ix_lesson_assignments_class_status", "lesson_assignments", ["class_id", "status"])
    op.create_index("ix_lesson_assignments_lesson", "lesson_assignments", ["lesson_id"])

    op.create_table(
        "password_reset_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_digest", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_digest"),
    )
    op.create_index("ix_password_reset_tokens_user_created", "password_reset_tokens", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_password_reset_tokens_user_created", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
    op.drop_index("ix_lesson_assignments_lesson", table_name="lesson_assignments")
    op.drop_index("ix_lesson_assignments_class_status", table_name="lesson_assignments")
    op.drop_index("ix_lesson_assignments_student_status", table_name="lesson_assignments")
    op.drop_table("lesson_assignments")
    op.drop_index("ix_messages_thread_created", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_message_threads_student_last", table_name="message_threads")
    op.drop_index("ix_message_threads_school_last", table_name="message_threads")
    op.drop_table("message_threads")
    op.drop_index("ix_notifications_recipient_unread", table_name="notifications")
    op.drop_index("ix_notifications_recipient_created", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_concepts_subject_name", table_name="concepts")
    op.drop_index("ix_concepts_school_name", table_name="concepts")
    op.drop_table("concepts")
    op.drop_column("users", "baseline_profile")
