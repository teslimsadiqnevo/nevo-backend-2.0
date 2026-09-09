"""Let a roster sync say that it is still running.

Revision ID: 20260909_0046
Revises: 20260909_0045
Create Date: 2026-09-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260909_0046"
down_revision: str | Sequence[str] | None = "20260909_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A sync walks every class and every member of every class through the
    # provider's API, which for a large school is minutes. The run row was
    # only written once that finished, so a sync in progress was invisible
    # and a sync that died left nothing behind.
    op.execute("ALTER TYPE roster_sync_status ADD VALUE IF NOT EXISTS 'running'")


def downgrade() -> None:
    # Postgres cannot drop a value from an enum without rewriting the type,
    # and nothing reads 'running' once the code is rolled back.
    pass
