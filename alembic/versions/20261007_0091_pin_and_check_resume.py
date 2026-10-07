"""Separate cleared PINs from onboarding and persist after-lesson check resume.

Revision ID: 20261007_0091
Revises: 20261005_0090
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261007_0091"
down_revision = "20261005_0090"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("pin_cleared_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "lesson_progress",
        sa.Column("check_position", sa.Integer(), nullable=True),
    )
    op.add_column(
        "lesson_progress",
        sa.Column("check_resumable_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_lesson_progress_check_position_non_negative",
        "lesson_progress",
        "check_position IS NULL OR check_position >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_lesson_progress_check_position_non_negative",
        "lesson_progress",
        type_="check",
    )
    op.drop_column("lesson_progress", "check_resumable_until")
    op.drop_column("lesson_progress", "check_position")
    op.drop_column("users", "pin_cleared_at")
