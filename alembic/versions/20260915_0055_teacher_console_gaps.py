"""Carry a teacher's note with a lesson assignment.

Revision ID: 20260915_0055
Revises: 20260911_0054
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260915_0055"
down_revision: str | Sequence[str] | None = "20260911_0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("lesson_assignments", sa.Column("note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("lesson_assignments", "note")
