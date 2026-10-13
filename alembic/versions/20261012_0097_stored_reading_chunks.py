"""Store ingest-time reading chunk boundaries.

Revision ID: 20261012_0097
Revises: 20261012_0096
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261012_0097"
down_revision = "20261012_0096"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lesson_segments",
        sa.Column(
            "reading_chunks",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("lesson_segments", "reading_chunks")
