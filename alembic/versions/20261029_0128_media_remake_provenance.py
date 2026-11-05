"""Persist when a teacher requested a media remake."""

import sqlalchemy as sa

from alembic import op

revision = "20261029_0128"
down_revision = "20261027_0127"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("deferred_lesson_media", sa.Column("remade_at", sa.DateTime(timezone=True)))


def downgrade():
    op.drop_column("deferred_lesson_media", "remade_at")
