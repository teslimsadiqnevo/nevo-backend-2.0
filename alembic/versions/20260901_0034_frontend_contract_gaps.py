"""Make assignments idempotent and give segments a duration.

Revision ID: 20260901_0034
Revises: 20260831_0033
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260901_0034"
down_revision: str | Sequence[str] | None = "20260831_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lesson_segments",
        sa.Column("estimated_minutes", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "lessons",
        sa.Column("estimated_minutes", sa.Integer(), server_default="0", nullable=False),
    )

    # The un-idempotent POST /assignments created duplicates before the unique
    # index existed. Collapse them first — keeping the earliest of each group,
    # which is the one the teacher's original request created — or the index
    # cannot be built.
    op.execute(
        """
        DELETE FROM lesson_assignments a
        USING lesson_assignments b
        WHERE a.lesson_id = b.lesson_id
          AND a.student_id = b.student_id
          AND a.available_from IS NOT DISTINCT FROM b.available_from
          AND (a.assigned_at, a.id) > (b.assigned_at, b.id)
        """
    )
    op.create_index(
        "uq_lesson_assignments_lesson_student_release",
        "lesson_assignments",
        ["lesson_id", "student_id", "available_from"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_lesson_assignments_lesson_student_release",
        table_name="lesson_assignments",
    )
    op.drop_column("lessons", "estimated_minutes")
    op.drop_column("lesson_segments", "estimated_minutes")
