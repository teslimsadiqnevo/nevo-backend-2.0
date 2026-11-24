"""A /me learner buys a month, and nothing about how they paid is kept.

/me, Phase 4. One row per checkout a learner starts. The webhook, never the
redirect back from Paystack, turns a pending row into a paid month.

There is deliberately no column here that could hold a card, an
authorization code, a customer code or any other reusable instrument (Lydia,
22 November 2026: Nevo stores no reusable payment token for any customer,
school or individual). No auto-renewal: a month lapses and the learner buys
again; reminder_sent_at records the reminder before it does.

0153, 24 November 2026.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261124_0153"
down_revision = "20261124_0152"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "me_purchases",
        sa.Column(
            "id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "learner_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("tier_key", sa.String(20), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("reference", sa.String(100), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("provider_reference", sa.String(100), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'success', 'failed', 'abandoned')",
            name="status_known",
        ),
        sa.CheckConstraint(
            "(status = 'success') = (period_start IS NOT NULL AND period_end IS NOT NULL)",
            name="a_paid_month_has_a_period",
        ),
    )
    op.create_index(
        "ix_me_purchases_learner_period", "me_purchases", ["learner_id", "period_end"]
    )


def downgrade() -> None:
    op.drop_index("ix_me_purchases_learner_period", table_name="me_purchases")
    op.drop_table("me_purchases")
