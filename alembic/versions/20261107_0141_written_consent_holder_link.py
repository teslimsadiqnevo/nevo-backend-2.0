"""Record the linked adult named as holder of written consent."""

import sqlalchemy as sa

from alembic import op

revision = "20261107_0141"
down_revision = "20261107_0140"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "consent_records",
        sa.Column("consent_holder_parent_link_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_consent_records_holder_parent_link",
        "consent_records",
        "parent_links",
        ["consent_holder_parent_link_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade():
    op.drop_constraint(
        "fk_consent_records_holder_parent_link", "consent_records", type_="foreignkey"
    )
    op.drop_column("consent_records", "consent_holder_parent_link_id")
