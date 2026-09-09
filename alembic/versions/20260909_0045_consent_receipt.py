"""Send a parent a copy of the consent they gave.

Revision ID: 20260909_0045
Revises: 20260908_0044
Create Date: 2026-09-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260909_0045"
down_revision: str | Sequence[str] | None = "20260908_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

kind_enum = postgresql.ENUM("request", "receipt", name="consent_notification_kind")


def upgrade() -> None:
    kind_enum.create(op.get_bind(), checkfirst=True)
    # The outbox only ever carried the request. A consent page that says a
    # copy has been sent, when none is, spends the credibility the page
    # exists to earn.
    op.add_column(
        "consent_notification_outbox",
        sa.Column("kind", kind_enum, nullable=False, server_default="request"),
    )
    # One row per invitation becomes one row per invitation per kind: the
    # constraint exists to stop a request being queued twice, and the receipt
    # is a second thing to send, not a second copy of the first.
    op.drop_constraint(
        "uq_consent_notification_outbox_invitation_id",
        "consent_notification_outbox",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_consent_notification_outbox_invitation_kind",
        "consent_notification_outbox",
        ["invitation_id", "kind"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_consent_notification_outbox_invitation_kind",
        "consent_notification_outbox",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_consent_notification_outbox_invitation_id",
        "consent_notification_outbox",
        ["invitation_id"],
    )
    op.drop_column("consent_notification_outbox", "kind")
    kind_enum.drop(op.get_bind(), checkfirst=True)
