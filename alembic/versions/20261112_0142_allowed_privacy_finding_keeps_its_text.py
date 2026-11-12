"""Keep the text behind a privacy finding we let through.

Lydia's first condition on Option A (12 November): a privacy_abuse finding on
Nevo's own lesson text no longer blocks, but it is still recorded with the
text, so a true positive would show.

Only those findings carry it. Recording the material for every safety decision
would store every lesson in the product several times over - there are 1,648
decisions against 47 parse runs - and the ones that need a human to look are
the ones we decided not to act on.

Revision ID: 20261112_0142
Revises: 20261107_0141
"""

import sqlalchemy as sa

from alembic import op

revision = "20261112_0142"
down_revision = "20261107_0141"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_safety_events",
        sa.Column("allowed_material", sa.Text(), nullable=True),
    )
    # The review queue: findings we allowed through and nobody has read yet.
    op.create_index(
        "ix_content_safety_events_allowed_material",
        "content_safety_events",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("allowed_material IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_content_safety_events_allowed_material",
        table_name="content_safety_events",
    )
    op.drop_column("content_safety_events", "allowed_material")
