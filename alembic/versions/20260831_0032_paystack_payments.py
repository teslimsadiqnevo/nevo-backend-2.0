"""Add Paystack transaction and webhook reconciliation tables.

Revision ID: 20260831_0032
Revises: 20260831_0031
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260831_0032"
down_revision: str | Sequence[str] | None = "20260831_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

payment_transaction_status = postgresql.ENUM(
    "pending",
    "success",
    "failed",
    "abandoned",
    name="payment_transaction_status",
    create_type=False,
)
webhook_event_status = postgresql.ENUM(
    "received",
    "processed",
    "ignored",
    "failed",
    name="webhook_event_status",
    create_type=False,
)
pricing_currency = postgresql.ENUM(name="pricing_currency", create_type=False)


def upgrade() -> None:
    payment_transaction_status.create(op.get_bind(), checkfirst=True)
    webhook_event_status.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "billing_payment_methods",
        sa.Column("is_reusable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "billing_payment_methods",
        sa.Column("processor_customer_code", sa.String(255)),
    )

    op.create_table(
        "payment_transactions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "school_id",
            sa.Uuid(),
            sa.ForeignKey("schools.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "invoice_id",
            sa.Uuid(),
            sa.ForeignKey("invoices.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reference", sa.String(120), nullable=False),
        sa.Column("provider", sa.String(40), server_default="paystack", nullable=False),
        sa.Column("provider_reference", sa.String(120)),
        sa.Column(
            "status",
            payment_transaction_status,
            server_default="pending",
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", pricing_currency, nullable=False),
        sa.Column("authorization_url", sa.Text()),
        sa.Column(
            "initiated_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("reference", name="uq_payment_transactions_reference"),
        sa.CheckConstraint("amount >= 0", name="payment_transaction_amount_nonnegative"),
        sa.CheckConstraint(
            "amount_minor >= 0",
            name="payment_transaction_amount_minor_nonnegative",
        ),
        sa.CheckConstraint(
            "(status = 'success') = (paid_at IS NOT NULL)",
            name="payment_transaction_paid_status_matches_paid_at",
        ),
    )
    op.create_index(
        "ix_payment_transactions_school_created",
        "payment_transactions",
        ["school_id", "created_at"],
    )
    op.create_index(
        "ix_payment_transactions_invoice",
        "payment_transactions",
        ["invoice_id"],
    )

    op.create_table(
        "payment_webhook_events",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("provider", sa.String(40), server_default="paystack", nullable=False),
        sa.Column("event_key", sa.String(160), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", webhook_event_status, server_default="received", nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "provider",
            "event_key",
            name="uq_payment_webhook_events_provider_key",
        ),
    )
    op.create_index(
        "ix_payment_webhook_events_status",
        "payment_webhook_events",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("payment_webhook_events")
    op.drop_table("payment_transactions")
    op.drop_column("billing_payment_methods", "processor_customer_code")
    op.drop_column("billing_payment_methods", "is_reusable")
    webhook_event_status.drop(op.get_bind(), checkfirst=True)
    payment_transaction_status.drop(op.get_bind(), checkfirst=True)
