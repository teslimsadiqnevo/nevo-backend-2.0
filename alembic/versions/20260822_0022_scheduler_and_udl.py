"""Add FSRS concept scheduling.

Revision ID: 20260822_0022
Revises: 20260822_0021
Create Date: 2026-08-22 00:22:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260822_0022"
down_revision: str | None = "20260822_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "student_concept_scheduling",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("concept_id", sa.Uuid(), nullable=False),
        sa.Column("stability", sa.Float(), nullable=False),
        sa.Column("difficulty", sa.Float(), nullable=False),
        sa.Column("last_review", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_review_due", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("stability > 0", name="scheduling_stability_positive"),
        sa.CheckConstraint(
            "difficulty BETWEEN 1 AND 10",
            name="scheduling_difficulty_range",
        ),
        sa.CheckConstraint(
            "review_count >= 0",
            name="scheduling_review_count_nonnegative",
        ),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "student_id",
            "concept_id",
            name="uq_student_concept_scheduling_student_concept",
        ),
    )
    op.create_index(
        "ix_student_concept_scheduling_student",
        "student_concept_scheduling",
        ["student_id"],
    )
    op.create_index(
        "ix_student_concept_scheduling_due",
        "student_concept_scheduling",
        ["next_review_due"],
    )
    op.create_index(
        "ix_student_concept_scheduling_student_due",
        "student_concept_scheduling",
        ["student_id", "next_review_due"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_student_concept_scheduling_student_due",
        table_name="student_concept_scheduling",
    )
    op.drop_index(
        "ix_student_concept_scheduling_due",
        table_name="student_concept_scheduling",
    )
    op.drop_index(
        "ix_student_concept_scheduling_student",
        table_name="student_concept_scheduling",
    )
    op.drop_table("student_concept_scheduling")
