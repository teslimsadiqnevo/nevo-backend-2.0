"""Probe items generated from uploaded lessons, and what children answered.

The probe was specified as an adaptive knowledge probe that seeds the knowledge
graph entry point per subject. It was not one: sixteen items sat hardcoded in
the front end with a local answer key, no difficulty attached and no adaptation
possible - and an answer key on the device is a probe a child can read.

Items are scoped to the school because they are generated from that school's
own uploaded lessons. One school's items never serve another school's children.

Responses are kept because difficulty is learned from them. Without the
responses the difficulty column can only ever hold the estimate it was written
with.

Revision ID: 20260929_0085
Revises: 20260929_0084
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260929_0085"
down_revision: str | Sequence[str] | None = "20260929_0084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "probe_items",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("school_subject_id", sa.Uuid(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("correct_option", sa.String(length=80), nullable=False),
        sa.Column("band", sa.String(length=20), nullable=True),
        sa.Column("concept_id", sa.Uuid(), nullable=True),
        sa.Column("lesson_id", sa.Uuid(), nullable=True),
        sa.Column("difficulty", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("times_answered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("times_correct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retired", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["school_subject_id"], ["school_subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_probe_items_school_subject", "probe_items", ["school_id", "school_subject_id"]
    )
    op.create_index("ix_probe_items_difficulty", "probe_items", ["school_subject_id", "difficulty"])
    op.create_table(
        "probe_responses",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("school_subject_id", sa.Uuid(), nullable=False),
        sa.Column("probe_item_id", sa.Uuid(), nullable=False),
        sa.Column("chosen_option", sa.String(length=80), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("difficulty_at_the_time", sa.Float(), nullable=False),
        sa.Column(
            "answered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["school_subject_id"], ["school_subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["probe_item_id"], ["probe_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_probe_responses_student_subject",
        "probe_responses",
        ["student_id", "school_subject_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_probe_responses_student_subject", "probe_responses")
    op.drop_table("probe_responses")
    op.drop_index("ix_probe_items_difficulty", "probe_items")
    op.drop_index("ix_probe_items_school_subject", "probe_items")
    op.drop_table("probe_items")
