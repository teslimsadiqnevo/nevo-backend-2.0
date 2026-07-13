"""Add lesson sessions for signal ingestion.

Revision ID: 20260705_0009
Revises: 20260705_0008
Create Date: 2026-07-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260705_0009"
down_revision: str | Sequence[str] | None = "20260705_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

lesson_completion_status_enum = postgresql.ENUM(
    "in_progress",
    "completed",
    "exited",
    name="lesson_completion_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    lesson_completion_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "lesson_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "student_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("lesson_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "completion_status",
            lesson_completion_status_enum,
            nullable=False,
            server_default=sa.text("'in_progress'"),
        ),
        sa.Column("exit_position", sa.String(length=120), nullable=True),
        sa.Column(
            "break_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "proactive_adjustments_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at",
            name="ended_at_after_started_at",
        ),
        sa.CheckConstraint(
            "break_count >= 0 AND proactive_adjustments_count >= 0",
            name="counters_non_negative",
        ),
    )
    op.create_index(
        "ix_lesson_sessions_student_started_at",
        "lesson_sessions",
        ["student_id", "started_at"],
    )
    op.create_index(
        "ix_lesson_sessions_lesson_started_at",
        "lesson_sessions",
        ["lesson_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_lesson_sessions_lesson_started_at",
        table_name="lesson_sessions",
    )
    op.drop_index(
        "ix_lesson_sessions_student_started_at",
        table_name="lesson_sessions",
    )
    op.drop_table("lesson_sessions")
    lesson_completion_status_enum.drop(op.get_bind(), checkfirst=True)

