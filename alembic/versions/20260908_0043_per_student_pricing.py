"""Hold per-student pricing on the school itself.

Revision ID: 20260908_0043
Revises: 20260907_0042
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260908_0043"
down_revision: str | Sequence[str] | None = "20260907_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

pricing_plan_enum = postgresql.ENUM("annual", "per_term", name="pricing_plan")


def upgrade() -> None:
    # asyncpg rejects multi-statement execute, so each statement stands alone.
    pricing_plan_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "schools",
        sa.Column(
            "pricing_plan",
            pricing_plan_enum,
            nullable=False,
            server_default="annual",
        ),
    )
    # Nullable: a school with no negotiated rate falls back to the published
    # one for its plan, so the rate card lives in one place rather than being
    # copied onto every row at sign-up.
    op.add_column(
        "schools",
        sa.Column("per_student_rate", sa.Numeric(12, 2), nullable=True),
    )
    op.create_check_constraint(
        "per_student_rate_nonnegative",
        "schools",
        "per_student_rate IS NULL OR per_student_rate >= 0",
    )
    # subscription_tier, enrollment_band and contract_value stay on the table.
    # They are off the API now, but they are the only record of what the
    # schools signed before this ruling, and nothing reads them into pricing.


def downgrade() -> None:
    op.drop_constraint("per_student_rate_nonnegative", "schools", type_="check")
    op.drop_column("schools", "per_student_rate")
    op.drop_column("schools", "pricing_plan")
    pricing_plan_enum.drop(op.get_bind(), checkfirst=True)
