"""A segment says which concept it teaches. SCRUM-177, ask B25.

Absent until now, so per-concept help could not adapt inside the calculation
solver - it could ask about the sum in front of the child but not about the
idea they were stuck on - and a check-in answer could only be attributed to a
concept through whichever checkpoint happened to carry one.

Nullable, and left null on every existing row. A segment written before the
column existed has no concept recorded anywhere, and guessing one from the
lesson's title would put a wrong attribution into a child's mastery.

Revision ID: 20261005_0089
Revises: 20261001_0088
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261005_0089"
down_revision = "20261001_0088"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lesson_segments", sa.Column("concept_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_lesson_segments_concept_id_concepts",
        "lesson_segments",
        "concepts",
        ["concept_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_lesson_segments_concept",
        "lesson_segments",
        ["concept_id"],
        postgresql_where=sa.text("concept_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_lesson_segments_concept", table_name="lesson_segments")
    op.drop_constraint(
        "fk_lesson_segments_concept_id_concepts", "lesson_segments", type_="foreignkey"
    )
    op.drop_column("lesson_segments", "concept_id")
