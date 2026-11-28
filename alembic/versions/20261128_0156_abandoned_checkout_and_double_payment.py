"""An abandoned checkout can be finished; a double payment is told and logged.

Lydia, 28 November 2026. Abandoned is no longer shown as failed: Paystack's
page is still live and payable, and a learner told it failed pays again. So:

checkout_url       Paystack's hosted page for this checkout, kept so an
                   abandoned one can be reopened and finished rather than a
                   second one started. A page link, not an instrument: it
                   cannot charge anyone, and it holds no card or token.
replaces_reference The checkout still unfinished (waiting or abandoned) when
                   this one was started. It is how two payments for one
                   intention are recognised if both go through.
double_paid_at     Set on the second of such a pair to succeed. Both months
                   are kept (no automatic refund).
double_paid_seen_at     The learner has seen the in-app notice.
double_paid_alerted_at  The team has been emailed about it.

0156, 28 November 2026.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261128_0156"
down_revision = "20261124_0155"
branch_labels = None
depends_on = None

_TIMES = ("double_paid_at", "double_paid_seen_at", "double_paid_alerted_at")


def upgrade() -> None:
    op.add_column("me_purchases", sa.Column("checkout_url", sa.Text(), nullable=True))
    op.add_column("me_purchases", sa.Column("replaces_reference", sa.String(100), nullable=True))
    for name in _TIMES:
        op.add_column("me_purchases", sa.Column(name, sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for name in reversed(_TIMES):
        op.drop_column("me_purchases", name)
    op.drop_column("me_purchases", "replaces_reference")
    op.drop_column("me_purchases", "checkout_url")
