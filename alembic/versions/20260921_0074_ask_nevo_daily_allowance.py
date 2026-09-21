"""Ask Nevo is capped by what it spends, not by how many chats were opened.

"Ten conversations a day" bounds nothing: a conversation is one short
question or twenty long turns, and the two differ in cost by two orders of
magnitude. Ask Nevo is the only part of the product that calls a model while
a child is waiting, so the number that has to hold is money.

Revision ID: 20260921_0074
Revises: 20260921_0073
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260921_0074"
down_revision: str | Sequence[str] | None = "20260921_0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = postgresql.ENUM(
    "student",
    "teacher",
    "parent",
    "admin",
    name="ask_nevo_role",
    create_type=False,
)


def upgrade() -> None:
    op.create_table(
        "ask_nevo_daily_usage",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        # The school day in Lagos rather than a UTC date: a day that turns
        # over at one in the morning locally is nobody's idea of a new day.
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("role", ROLE, nullable=False),
        sa.Column("units_spent", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("exchanges", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "units_spent >= 0 AND exchanges >= 0",
            name="ask_nevo_usage_non_negative",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_ask_nevo_daily_usage_actor_day",
        "ask_nevo_daily_usage",
        ["actor_user_id", "usage_date"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_ask_nevo_daily_usage_actor_day", table_name="ask_nevo_daily_usage")
    op.drop_table("ask_nevo_daily_usage")
