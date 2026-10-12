"""Associate intervention recommendations with a lesson.

Revision ID: 20261012_0095
Revises: 20261009_0094
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261012_0095"
down_revision = "20261009_0094"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "intervention_recommendations",
        sa.Column("lesson_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_intervention_recommendations_lesson_id_lessons",
        "intervention_recommendations",
        "lessons",
        ["lesson_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_intervention_recommendations_lesson_id",
        "intervention_recommendations",
        ["lesson_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_intervention_recommendations_lesson_id",
        table_name="intervention_recommendations",
    )
    op.drop_constraint(
        "fk_intervention_recommendations_lesson_id_lessons",
        "intervention_recommendations",
        type_="foreignkey",
    )
    op.drop_column("intervention_recommendations", "lesson_id")
