"""Move legacy indefinite retention to the twelve-month policy.

Revision ID: 20261009_0094
Revises: 20261008_0093
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261009_0094"
down_revision = "20261008_0093"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE schools
            SET retention_policy = 'contract', data_retention_days = 365
            WHERE retention_policy = 'indefinite'
               OR data_retention_days > 3650
            """
        )
    )


def downgrade() -> None:
    # The previous indefinite settings varied by school and cannot be
    # reconstructed safely from the normalised value.
    pass
