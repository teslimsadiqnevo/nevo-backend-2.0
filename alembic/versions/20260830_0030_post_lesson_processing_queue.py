"""Make post-lesson intelligence processing durable.

Revision ID: 20260830_0030
Revises: 20260829_0029
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260830_0030"
down_revision: str | Sequence[str] | None = "20260829_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "upload_source_blobs",
        sa.Column(
            "upload_id",
            sa.Uuid(),
            sa.ForeignKey("upload_jobs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "notification_email_deliveries",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "notification_id",
            sa.Uuid(),
            sa.ForeignKey("notifications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(24), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text()),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "uq_notification_email_deliveries_notification",
        "notification_email_deliveries",
        ["notification_id"],
        unique=True,
    )
    op.create_index(
        "ix_notification_email_deliveries_due",
        "notification_email_deliveries",
        ["status", "next_attempt_at"],
    )
    op.add_column("lessons", sa.Column("subject", sa.String(120)))
    op.add_column(
        "lesson_assignments",
        sa.Column("available_from", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "message_thread_reads",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "thread_id",
            sa.Uuid(),
            sa.ForeignKey("message_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "last_read_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "uq_message_thread_reads_thread_user",
        "message_thread_reads",
        ["thread_id", "user_id"],
        unique=True,
    )
    op.add_column(
        "attention_flags",
        sa.Column(
            "evidence_series",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "attention_flags",
        sa.Column(
            "action_targets",
            postgresql.JSONB(),
            server_default=sa.text("'[\"view_student\", \"open_recommendation\"]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "school_sso_configurations",
        sa.Column("oauth_credential_ciphertext", sa.Text()),
    )
    op.add_column(
        "post_lesson_processing",
        sa.Column("status", sa.String(24), server_default="completed", nullable=False),
    )
    op.add_column(
        "post_lesson_processing",
        sa.Column("attempt_count", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "post_lesson_processing",
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "post_lesson_processing",
        sa.Column("profile_updated", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column(
        "post_lesson_processing",
        sa.Column("flags_evaluated", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column("post_lesson_processing", sa.Column("last_error", sa.Text()))
    op.add_column(
        "post_lesson_processing",
        sa.Column("processed_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        "UPDATE post_lesson_processing SET processed_at = completed_at "
        "WHERE status = 'completed'"
    )
    op.create_index(
        "ix_post_lesson_processing_due",
        "post_lesson_processing",
        ["status", "next_attempt_at"],
    )
    op.alter_column("post_lesson_processing", "status", server_default="pending")
    op.alter_column("post_lesson_processing", "attempt_count", server_default="0")
    op.alter_column(
        "post_lesson_processing", "profile_updated", server_default=sa.text("false")
    )
    op.alter_column(
        "post_lesson_processing", "flags_evaluated", server_default=sa.text("false")
    )


def downgrade() -> None:
    op.drop_table("upload_source_blobs")
    op.drop_table("notification_email_deliveries")
    op.drop_table("message_thread_reads")
    op.drop_index("ix_post_lesson_processing_due", table_name="post_lesson_processing")
    for column in (
        "processed_at",
        "last_error",
        "flags_evaluated",
        "profile_updated",
        "next_attempt_at",
        "attempt_count",
        "status",
    ):
        op.drop_column("post_lesson_processing", column)
    op.drop_column("school_sso_configurations", "oauth_credential_ciphertext")
    op.drop_column("lesson_assignments", "available_from")
    op.drop_column("lessons", "subject")
    op.drop_column("attention_flags", "action_targets")
    op.drop_column("attention_flags", "evidence_series")
