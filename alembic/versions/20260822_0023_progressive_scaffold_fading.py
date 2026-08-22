"""Add progressive scaffold fading state and logs.

Revision ID: 20260822_0023
Revises: 20260822_0022
Create Date: 2026-08-22 00:23:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260822_0023"
down_revision: str | None = "20260822_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

scaffold_intensity_enum = postgresql.ENUM(
    "full_support",
    "partial_support",
    "hints_only",
    "independent",
    name="scaffold_intensity",
)
scaffold_outcome_enum = postgresql.ENUM(
    "correct",
    "struggled",
    name="scaffold_outcome",
)


def upgrade() -> None:
    bind = op.get_bind()
    scaffold_intensity_enum.create(bind, checkfirst=True)
    scaffold_outcome_enum.create(bind, checkfirst=True)

    op.create_table(
        "student_concept_scaffold_states",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("concept_id", sa.Uuid(), nullable=False),
        sa.Column(
            "current_intensity",
            scaffold_intensity_enum,
            server_default="full_support",
            nullable=False,
        ),
        sa.Column(
            "consecutive_correct",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "response_time_improvement_streak",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "reduced_hint_streak",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("last_response_time_ms", sa.Integer(), nullable=True),
        sa.Column("last_hint_count", sa.Integer(), nullable=True),
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
        sa.CheckConstraint(
            "consecutive_correct >= 0",
            name="scaffold_state_consecutive_correct_nonnegative",
        ),
        sa.CheckConstraint(
            "response_time_improvement_streak >= 0",
            name="scaffold_state_response_time_streak_nonnegative",
        ),
        sa.CheckConstraint(
            "reduced_hint_streak >= 0",
            name="scaffold_state_reduced_hint_streak_nonnegative",
        ),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "student_id",
            "concept_id",
            name="uq_student_concept_scaffold_state_student_concept",
        ),
    )
    op.create_index(
        "ix_student_concept_scaffold_states_student",
        "student_concept_scaffold_states",
        ["student_id"],
    )
    op.create_index(
        "ix_student_concept_scaffold_states_student_concept",
        "student_concept_scaffold_states",
        ["student_id", "concept_id"],
    )

    op.create_table(
        "scaffold_problem_logs",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("concept_id", sa.Uuid(), nullable=False),
        sa.Column("problem_id", sa.String(length=120), nullable=False),
        sa.Column("scaffold_intensity", scaffold_intensity_enum, nullable=False),
        sa.Column("outcome", scaffold_outcome_enum, nullable=False),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column("expected_response_time_ms", sa.Integer(), nullable=True),
        sa.Column("hint_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_scaffold_intensity", scaffold_intensity_enum, nullable=False),
        sa.Column(
            "level_changed",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column("change_reason", sa.String(length=160), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "hint_count >= 0",
            name="scaffold_log_hint_count_nonnegative",
        ),
        sa.CheckConstraint(
            "response_time_ms IS NULL OR response_time_ms >= 0",
            name="scaffold_log_response_time_nonnegative",
        ),
        sa.CheckConstraint(
            "expected_response_time_ms IS NULL OR expected_response_time_ms > 0",
            name="scaffold_log_expected_time_positive",
        ),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scaffold_problem_logs_student_created",
        "scaffold_problem_logs",
        ["student_id", "created_at"],
    )
    op.create_index(
        "ix_scaffold_problem_logs_concept_created",
        "scaffold_problem_logs",
        ["concept_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scaffold_problem_logs_concept_created",
        table_name="scaffold_problem_logs",
    )
    op.drop_index(
        "ix_scaffold_problem_logs_student_created",
        table_name="scaffold_problem_logs",
    )
    op.drop_table("scaffold_problem_logs")
    op.drop_index(
        "ix_student_concept_scaffold_states_student_concept",
        table_name="student_concept_scaffold_states",
    )
    op.drop_index(
        "ix_student_concept_scaffold_states_student",
        table_name="student_concept_scaffold_states",
    )
    op.drop_table("student_concept_scaffold_states")
    scaffold_outcome_enum.drop(op.get_bind(), checkfirst=True)
    scaffold_intensity_enum.drop(op.get_bind(), checkfirst=True)
