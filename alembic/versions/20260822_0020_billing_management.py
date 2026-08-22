"""Add billing management schema.

Revision ID: 20260822_0020
Revises: 20260812_0019
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260822_0020"
down_revision: str | Sequence[str] | None = "20260812_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

subscription_tier_enum = postgresql.ENUM(
    "boutique",
    "mid_market",
    "premium",
    "enterprise",
    name="subscription_tier",
    create_type=False,
)
invoice_status_enum = postgresql.ENUM(
    "paid",
    "pending",
    "overdue",
    name="invoice_status",
    create_type=False,
)
payment_method_type_enum = postgresql.ENUM(
    "card",
    "direct_debit",
    name="payment_method_type",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    subscription_tier_enum.create(bind, checkfirst=True)
    invoice_status_enum.create(bind, checkfirst=True)
    payment_method_type_enum.create(bind, checkfirst=True)

    op.create_table(
        "billing_contacts",
        sa.Column(
            "id",
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
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("address_line1", sa.String(length=255), nullable=False),
        sa.Column("address_line2", sa.String(length=255), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=False),
        sa.Column("region", sa.String(length=120), nullable=True),
        sa.Column("postal_code", sa.String(length=40), nullable=True),
        sa.Column("country", sa.String(length=120), nullable=False),
        sa.Column(
            "updated_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("school_id", name="uq_billing_contacts_school_id"),
    )

    op.add_column(
        "schools",
        sa.Column("subscription_tier", subscription_tier_enum, nullable=True),
    )
    op.add_column(
        "schools",
        sa.Column("contract_value", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "schools",
        sa.Column("contract_start", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "schools",
        sa.Column("contract_end", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "schools",
        sa.Column("billing_contact_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_schools_billing_contact_id_billing_contacts",
        "schools",
        "billing_contacts",
        ["billing_contact_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "contract_value_nonnegative",
        "schools",
        "contract_value IS NULL OR contract_value >= 0",
    )
    op.create_check_constraint(
        "contract_dates_ordered",
        "schools",
        "contract_start IS NULL OR contract_end IS NULL OR contract_end >= contract_start",
    )

    op.create_table(
        "billing_payment_methods",
        sa.Column(
            "id",
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
        sa.Column("method_type", payment_method_type_enum, nullable=False),
        sa.Column("processor_name", sa.String(length=80), nullable=True),
        sa.Column(
            "processor_payment_method_ref",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("last_four", sa.String(length=4), nullable=False),
        sa.Column("card_brand", sa.String(length=80), nullable=True),
        sa.Column("expiry_month", sa.Integer(), nullable=True),
        sa.Column("expiry_year", sa.Integer(), nullable=True),
        sa.Column("bank_name", sa.String(length=120), nullable=True),
        sa.Column("account_holder_name", sa.String(length=255), nullable=True),
        sa.Column(
            "updated_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("last_four ~ '^[0-9]{4}$'", name="last_four_digits"),
        sa.UniqueConstraint(
            "school_id",
            name="uq_billing_payment_methods_school_id",
        ),
    )

    op.create_table(
        "invoices",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("invoice_number", sa.String(length=80), nullable=False),
        sa.Column(
            "school_id",
            sa.Uuid(),
            sa.ForeignKey("schools.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("issued_at", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", invoice_status_enum, nullable=False),
        sa.Column("due_at", sa.Date(), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pdf_url", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("amount >= 0", name="invoice_amount_nonnegative"),
        sa.CheckConstraint(
            "(status = 'paid') = (paid_at IS NOT NULL)",
            name="paid_status_matches_paid_at",
        ),
        sa.UniqueConstraint("invoice_number", name="uq_invoices_invoice_number"),
    )
    op.create_index(
        "ix_invoices_school_issued",
        "invoices",
        ["school_id", "issued_at"],
    )
    op.create_index(
        "ix_invoices_school_status_due",
        "invoices",
        ["school_id", "status", "due_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_invoices_school_status_due", table_name="invoices")
    op.drop_index("ix_invoices_school_issued", table_name="invoices")
    op.drop_table("invoices")
    op.drop_table("billing_payment_methods")
    op.drop_constraint(
        op.f("ck_schools_contract_dates_ordered"),
        "schools",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_schools_contract_value_nonnegative"),
        "schools",
        type_="check",
    )
    op.drop_constraint(
        op.f("fk_schools_billing_contact_id_billing_contacts"),
        "schools",
        type_="foreignkey",
    )
    op.drop_column("schools", "billing_contact_id")
    op.drop_column("schools", "contract_end")
    op.drop_column("schools", "contract_start")
    op.drop_column("schools", "contract_value")
    op.drop_column("schools", "subscription_tier")
    op.drop_table("billing_contacts")
    payment_method_type_enum.drop(op.get_bind(), checkfirst=True)
    invoice_status_enum.drop(op.get_bind(), checkfirst=True)
    subscription_tier_enum.drop(op.get_bind(), checkfirst=True)
