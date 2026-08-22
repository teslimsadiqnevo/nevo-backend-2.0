"""Add hybrid AKT mastery schema.

Revision ID: 20260822_0021
Revises: 20260822_0020
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260822_0021"
down_revision: str | Sequence[str] | None = "20260822_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

failure_attribution_enum = postgresql.ENUM(
    "concept",
    "reading",
    "mixed",
    "none",
    name="mastery_failure_attribution",
    create_type=False,
)


def upgrade() -> None:
    failure_attribution_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "student_concept_mastery",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "student_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("concept_id", sa.Uuid(), nullable=False),
        sa.Column("mastery_probability_concept", sa.Float(), nullable=False),
        sa.Column("mastery_probability_reading", sa.Float(), nullable=False),
        sa.Column(
            "attention_weights",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "guess_probability",
            sa.Float(),
            nullable=False,
            server_default="0.2",
        ),
        sa.Column(
            "slip_probability",
            sa.Float(),
            nullable=False,
            server_default="0.1",
        ),
        sa.Column(
            "practice_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_response_correct", sa.Boolean(), nullable=True),
        sa.Column(
            "last_failure_attribution",
            failure_attribution_enum,
            nullable=False,
            server_default="none",
        ),
        sa.Column(
            "seeding_source",
            sa.String(length=80),
            nullable=False,
            server_default="default",
        ),
        sa.Column(
            "last_updated",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "mastery_probability_concept BETWEEN 0 AND 1",
            name="mastery_probability_concept_range",
        ),
        sa.CheckConstraint(
            "mastery_probability_reading BETWEEN 0 AND 1",
            name="mastery_probability_reading_range",
        ),
        sa.CheckConstraint(
            "guess_probability BETWEEN 0 AND 1",
            name="guess_probability_range",
        ),
        sa.CheckConstraint(
            "slip_probability BETWEEN 0 AND 1",
            name="slip_probability_range",
        ),
        sa.CheckConstraint(
            "practice_count >= 0",
            name="practice_count_nonnegative",
        ),
        sa.UniqueConstraint(
            "student_id",
            "concept_id",
            name="uq_student_concept_mastery_student_concept",
        ),
    )
    op.create_index(
        "ix_student_concept_mastery_student",
        "student_concept_mastery",
        ["student_id"],
    )
    op.create_index(
        "ix_student_concept_mastery_concept",
        "student_concept_mastery",
        ["concept_id"],
    )
    op.create_index(
        "ix_student_concept_mastery_student_concept",
        "student_concept_mastery",
        ["student_id", "concept_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_student_concept_mastery_student_concept",
        table_name="student_concept_mastery",
    )
    op.drop_index(
        "ix_student_concept_mastery_concept",
        table_name="student_concept_mastery",
    )
    op.drop_index(
        "ix_student_concept_mastery_student",
        table_name="student_concept_mastery",
    )
    op.drop_table("student_concept_mastery")
    failure_attribution_enum.drop(op.get_bind(), checkfirst=True)
