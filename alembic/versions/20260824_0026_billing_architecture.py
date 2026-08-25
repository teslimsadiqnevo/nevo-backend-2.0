"""Add billing pricing architecture.

Revision ID: 20260824_0026
Revises: 20260822_0025
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260824_0026"
down_revision: str | Sequence[str] | None = "20260822_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

pricing_currency_enum = postgresql.ENUM(
    "USD",
    "NGN",
    "GBP",
    name="pricing_currency",
    create_type=False,
)
contract_status_enum = postgresql.ENUM(
    "active",
    "suspended",
    "terminated",
    "pending_renewal",
    name="contract_status",
    create_type=False,
)
payment_source_enum = postgresql.ENUM(
    "direct",
    "sterling",
    "partner",
    name="payment_source",
    create_type=False,
)
subscription_tier_enum = postgresql.ENUM(
    "boutique",
    "mid_market",
    "premium",
    "enterprise",
    name="subscription_tier",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    pricing_currency_enum.create(bind, checkfirst=True)
    contract_status_enum.create(bind, checkfirst=True)
    payment_source_enum.create(bind, checkfirst=True)

    op.add_column(
        "schools",
        sa.Column(
            "payment_source",
            payment_source_enum,
            nullable=False,
            server_default="direct",
        ),
    )

    op.create_table(
        "subscription_tiers",
        sa.Column(
            "tier_id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tier_name", subscription_tier_enum, nullable=False),
        sa.Column("min_pupils", sa.Integer(), nullable=False),
        sa.Column("max_pupils", sa.Integer(), nullable=False),
        sa.Column("founding_partner_usd_rate", sa.Numeric(12, 2), nullable=False),
        sa.Column("commercial_usd_rate", sa.Numeric(12, 2), nullable=False),
        sa.Column("vat_rate", sa.Numeric(5, 2), nullable=False, server_default="7.50"),
        sa.UniqueConstraint("tier_name", name="uq_subscription_tiers_tier_name"),
        sa.CheckConstraint(
            "min_pupils >= 0",
            name="subscription_tier_min_pupils_valid",
        ),
        sa.CheckConstraint(
            "max_pupils >= min_pupils",
            name="subscription_tier_boundary",
        ),
        sa.CheckConstraint(
            "founding_partner_usd_rate >= 0 AND commercial_usd_rate >= 0",
            name="subscription_tier_rates_nonnegative",
        ),
        sa.CheckConstraint(
            "vat_rate >= 0",
            name="subscription_tier_vat_nonnegative",
        ),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO subscription_tiers (
                tier_name,
                min_pupils,
                max_pupils,
                founding_partner_usd_rate,
                commercial_usd_rate,
                vat_rate
            )
            VALUES
                ('boutique'::subscription_tier, 0, 250, 25000, 40000, 7.50),
                ('mid_market'::subscription_tier, 251, 500, 50000, 80000, 7.50),
                ('premium'::subscription_tier, 501, 800, 80000, 125000, 7.50),
                ('enterprise'::subscription_tier, 801, 999999, 140000, 220000, 7.50)
            ON CONFLICT (tier_name) DO NOTHING
            """
        )
    )

    op.create_table(
        "exchange_rates",
        sa.Column(
            "rate_id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source_currency", pricing_currency_enum, nullable=False),
        sa.Column("target_currency", pricing_currency_enum, nullable=False),
        sa.Column("conversion_rate", sa.Numeric(12, 6), nullable=False),
        sa.Column(
            "volatility_buffer_percent",
            sa.Numeric(4, 2),
            nullable=False,
            server_default="5.00",
        ),
        sa.Column("effective_start", sa.Date(), nullable=False),
        sa.Column("effective_end", sa.Date(), nullable=False),
        sa.CheckConstraint("conversion_rate > 0", name="exchange_rate_positive"),
        sa.CheckConstraint(
            "volatility_buffer_percent >= 0",
            name="exchange_rate_buffer_nonnegative",
        ),
        sa.CheckConstraint(
            "effective_end >= effective_start",
            name="exchange_rate_dates_ordered",
        ),
    )
    op.create_index(
        "ix_exchange_rates_pair_effective",
        "exchange_rates",
        ["source_currency", "target_currency", "effective_start", "effective_end"],
    )

    op.create_table(
        "contracts",
        sa.Column(
            "contract_id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "school_id",
            sa.Uuid(),
            sa.ForeignKey("schools.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tier_id",
            sa.Uuid(),
            sa.ForeignKey("subscription_tiers.tier_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "status",
            contract_status_enum,
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "is_founding_partner",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "payment_source",
            payment_source_enum,
            nullable=False,
            server_default="direct",
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("current_year_index", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "current_year_index BETWEEN 1 AND 6",
            name="contract_year_index_valid",
        ),
        sa.CheckConstraint("end_date >= start_date", name="contract_dates_valid"),
    )
    op.create_index("ix_contracts_school_status", "contracts", ["school_id", "status"])

    op.create_table(
        "step_up_schedules",
        sa.Column(
            "schedule_id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "contract_id",
            sa.Uuid(),
            sa.ForeignKey("contracts.contract_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("year_index", sa.Integer(), nullable=False),
        sa.Column("discount_percentage", sa.Numeric(5, 2), nullable=False),
        sa.UniqueConstraint(
            "contract_id",
            "year_index",
            name="uq_step_up_schedules_contract_year",
        ),
        sa.CheckConstraint("year_index BETWEEN 1 AND 6", name="step_up_year_valid"),
        sa.CheckConstraint(
            "discount_percentage BETWEEN 0 AND 100",
            name="step_up_discount_valid",
        ),
    )

    op.create_table(
        "billing_ledger",
        sa.Column(
            "invoice_id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "contract_id",
            sa.Uuid(),
            sa.ForeignKey("contracts.contract_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("billing_period_start", sa.Date(), nullable=False),
        sa.Column("billing_period_end", sa.Date(), nullable=False),
        sa.Column("amount_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "applied_discount_percent",
            sa.Numeric(5, 2),
            nullable=False,
            server_default="0.00",
        ),
        sa.Column("net_amount_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("vat_amount_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("total_with_vat_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("billed_currency", pricing_currency_enum, nullable=False),
        sa.Column(
            "fx_rate_applied",
            sa.Numeric(12, 6),
            nullable=False,
            server_default="1.000000",
        ),
        sa.Column("total_billed_local", sa.Numeric(12, 2), nullable=False),
        sa.Column("is_paid", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "billing_period_end >= billing_period_start",
            name="billing_ledger_period_valid",
        ),
        sa.CheckConstraint(
            "amount_usd >= 0 AND net_amount_usd >= 0 AND vat_amount_usd >= 0",
            name="billing_ledger_amounts_nonnegative",
        ),
        sa.CheckConstraint("fx_rate_applied > 0", name="billing_ledger_fx_positive"),
    )
    op.create_index(
        "ix_billing_ledger_contract_issued",
        "billing_ledger",
        ["contract_id", "issued_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_billing_ledger_contract_issued", table_name="billing_ledger")
    op.drop_table("billing_ledger")
    op.drop_table("step_up_schedules")
    op.drop_index("ix_contracts_school_status", table_name="contracts")
    op.drop_table("contracts")
    op.drop_index("ix_exchange_rates_pair_effective", table_name="exchange_rates")
    op.drop_table("exchange_rates")
    op.drop_table("subscription_tiers")
    op.drop_column("schools", "payment_source")
    payment_source_enum.drop(op.get_bind(), checkfirst=True)
    contract_status_enum.drop(op.get_bind(), checkfirst=True)
    pricing_currency_enum.drop(op.get_bind(), checkfirst=True)
