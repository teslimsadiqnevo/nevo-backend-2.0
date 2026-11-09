"""Allow several invoice contacts while retaining one primary checkout contact."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20261105_0133"
down_revision = "20261105_0132"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("uq_billing_contacts_school_id", "billing_contacts", type_="unique")
    op.create_unique_constraint(
        "uq_billing_contacts_school_email", "billing_contacts", ["school_id", "email"]
    )
    op.add_column(
        "invoices",
        sa.Column("activation_student_ids", JSONB(), nullable=False, server_default="[]"),
    )


def downgrade():
    connection = op.get_bind()
    duplicate = connection.exec_driver_sql(
        "SELECT 1 FROM billing_contacts GROUP BY school_id HAVING count(*) > 1 LIMIT 1"
    ).first()
    if duplicate:
        raise RuntimeError("Remove additional billing contacts before downgrading")
    op.drop_column("invoices", "activation_student_ids")
    op.drop_constraint("uq_billing_contacts_school_email", "billing_contacts", type_="unique")
    op.create_unique_constraint("uq_billing_contacts_school_id", "billing_contacts", ["school_id"])
