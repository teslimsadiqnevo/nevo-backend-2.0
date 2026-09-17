"""Put every notification in the category its type implies.

The email worker decides what to suppress by joining a user's preferences on
notifications.category, and its rule is to send when no preference matches. One
kind was being stored as the column default, "general", which is not one of the
seven categories a preference can be set for - so it matched nothing, and a
teacher who muted attention kept receiving attention emails.

The mapping is the same one the API reads from, so the column and the wire now
agree instead of differing by one write site.

Revision ID: 20260917_0059
Revises: 20260917_0058
Create Date: 2026-09-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260917_0059"
down_revision: str | Sequence[str] | None = "20260917_0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Kept as literal pairs rather than imported, because a migration has to keep
#: doing what it did on the day it ran even after the mapping moves on.
CATEGORY_BY_TYPE = {
    "attention_summary": "attention",
    "modality_shift": "attention",
    "pin_reset_requested": "account",
    "admin_welcome": "account",
    "consent_action_required": "consent",
    "roster_sync_completed": "reports",
    "roster_sync_needs_attention": "reports",
    "sso_needs_attention": "account",
    "invoice_issued": "billing",
}


def upgrade() -> None:
    for notification_type, category in CATEGORY_BY_TYPE.items():
        op.execute(
            f"UPDATE notifications SET category = '{category}' "
            f"WHERE type = '{notification_type}' AND category IS DISTINCT FROM '{category}'"
        )


def downgrade() -> None:
    # Nothing to undo: the previous values were wrong, and restoring them would
    # restore a mute that silences nothing.
    pass
