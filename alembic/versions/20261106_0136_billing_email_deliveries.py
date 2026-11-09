"""Queue invoice and reminder email to each billing contact."""

import sqlalchemy as sa

from alembic import op

revision = "20261106_0136"
down_revision = "20261030_0135"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "billing_email_deliveries",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "invoice_id",
            sa.Uuid(),
            sa.ForeignKey("invoices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_error", sa.Text()),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "invoice_id", "email", "kind", name="uq_billing_email_invoice_recipient_kind"
        ),
    )
    op.create_index(
        "ix_billing_email_due", "billing_email_deliveries", ["status", "next_attempt_at"]
    )


def downgrade():
    op.drop_index("ix_billing_email_due", table_name="billing_email_deliveries")
    op.drop_table("billing_email_deliveries")
