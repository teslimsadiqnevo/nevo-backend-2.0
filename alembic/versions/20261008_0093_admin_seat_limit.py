"""Give each school an enforceable admin-seat allowance.

Revision ID: 20261008_0093
Revises: 20261008_0092
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261008_0093"
down_revision = "20261008_0092"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "schools",
        sa.Column("admin_seat_limit", sa.Integer(), server_default="5", nullable=False),
    )
    op.create_check_constraint(
        "admin_seat_limit_positive",
        "schools",
        "admin_seat_limit > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "admin_seat_limit_positive",
        "schools",
        type_="check",
    )
    op.drop_column("schools", "admin_seat_limit")
