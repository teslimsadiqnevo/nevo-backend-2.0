"""Make an invoice explain its own amount.

Revision ID: 20260908_0044
Revises: 20260908_0043
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260908_0044"
down_revision: str | Sequence[str] | None = "20260908_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A per-student total is unreconstructable after the fact without the two
    # numbers it came from: head count moves every week, so "why is this
    # 32,250,000?" has no answer from the amount alone.
    op.add_column("invoices", sa.Column("student_count", sa.Integer(), nullable=True))
    op.add_column("invoices", sa.Column("per_student_rate", sa.Numeric(12, 2), nullable=True))
    op.add_column("invoices", sa.Column("total_before_vat", sa.Numeric(12, 2), nullable=True))
    op.add_column("invoices", sa.Column("vat_amount", sa.Numeric(12, 2), nullable=True))
    op.add_column("invoices", sa.Column("period_label", sa.String(80), nullable=True))
    # The amount had no currency at all, while payment transactions did. A
    # dollar invoice settled by a naira charge would have compared equal on
    # the number alone.
    op.add_column(
        "invoices",
        sa.Column(
            "currency",
            postgresql.ENUM(name="pricing_currency", create_type=False),
            nullable=False,
            server_default="NGN",
        ),
    )
    op.create_check_constraint(
        "invoice_student_count_nonnegative",
        "invoices",
        "student_count IS NULL OR student_count >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("invoice_student_count_nonnegative", "invoices", type_="check")
    op.drop_column("invoices", "currency")
    op.drop_column("invoices", "period_label")
    op.drop_column("invoices", "vat_amount")
    op.drop_column("invoices", "total_before_vat")
    op.drop_column("invoices", "per_student_rate")
    op.drop_column("invoices", "student_count")
