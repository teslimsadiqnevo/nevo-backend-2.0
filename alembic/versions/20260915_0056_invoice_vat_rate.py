"""Store the rate an invoice's VAT was charged at.

The invoice already keeps the working behind its total - head count, rate per
student, the amount before tax - because a total nobody can explain is no use
to a school's bursar months later. The one number missing was the tax rate,
which is also the one set by government rather than by us. If Nigeria moves
off 7.5%, every invoice issued before the change becomes unexplainable, and a
client showing the VAT line has nothing to put next to the amount.

Existing rows are backfilled at 7.50, which is the only rate this product has
ever charged.

Revision ID: 20260915_0056
Revises: 20260915_0055
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260915_0056"
down_revision: str | Sequence[str] | None = "20260915_0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column("vat_rate", sa.Numeric(5, 2), nullable=True),
    )
    # Only rows that carry a VAT amount were charged VAT at all. The rest are
    # pre-per-student invoices whose working was never stored, and inventing a
    # rate for them would be worse than leaving the field null.
    op.execute("UPDATE invoices SET vat_rate = 7.50 WHERE vat_amount IS NOT NULL")


def downgrade() -> None:
    op.drop_column("invoices", "vat_rate")
