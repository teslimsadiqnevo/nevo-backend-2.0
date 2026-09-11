"""Give a lesson an ending: a recap for the child and questions to close on.

Revision ID: 20260911_0051
Revises: 20260911_0050
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260911_0051"
down_revision: str | Sequence[str] | None = "20260911_0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A child finished their last segment and got a bare "Done". The screens
    # that should follow were built; nothing on the lesson carried anything
    # for them to render.
    op.add_column("lessons", sa.Column("recap", sa.Text(), nullable=True))
    op.add_column(
        "lessons",
        sa.Column(
            "assessment",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("lessons", "assessment")
    op.drop_column("lessons", "recap")
