"""A /me learner accepts the terms at sign-up; a lapsed month is told about.

Lydia, 24 November 2026.

Ruling D: an adult on /me is not asked a separate question about their
material leaving Nigeria, because accepting the terms at sign-up is them
agreeing to it for themselves. That only holds if the acceptance is
recorded, so users gains terms_accepted_at and terms_version. Null for every
school account, which accepts through its school's agreement instead.

Ruling F: two renewal reminders, seven days before and on the day the month
lapses. me_purchases.reminder_sent_at records the first; lapse_notice_sent_at
the second.

0155, 24 November 2026.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261124_0155"
down_revision = "20261124_0154"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("terms_version", sa.String(40), nullable=True))
    op.add_column(
        "me_purchases",
        sa.Column("lapse_notice_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("me_purchases", "lapse_notice_sent_at")
    op.drop_column("users", "terms_version")
    op.drop_column("users", "terms_accepted_at")
