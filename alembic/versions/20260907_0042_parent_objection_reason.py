"""Keep the reason a parent gives when they object.

Revision ID: 20260907_0042
Revises: 20260907_0041
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260907_0042"
down_revision: str | Sequence[str] | None = "20260907_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The consent screen draws a "Describe your concern" box. Without somewhere
    # to put the answer, the request that reaches the school is a bare type
    # with no account of what the parent actually objected to.
    op.add_column(
        "parent_data_requests",
        sa.Column("reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("parent_data_requests", "reason")
