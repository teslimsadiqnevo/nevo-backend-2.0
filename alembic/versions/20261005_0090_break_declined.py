"""A declined break is a reportable thing. Ask B40.

break_suggested said an offer was made and break_taken said it was accepted.
Nothing said it was refused, so the engine could not tell "not now" from no
answer and could offer again a minute later - which is the one response
guaranteed to annoy a child who is concentrating.

signal_event_type is a native enum, so a value the database will not accept
is a value the client drops at the door.

Revision ID: 20261005_0090
Revises: 20261005_0089
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261005_0090"
down_revision = "20261005_0089"
branch_labels = None
depends_on = None

NEW_VALUE = "break_declined"


def upgrade() -> None:
    statement = f"ALTER TYPE signal_event_type ADD VALUE IF NOT EXISTS '{NEW_VALUE}'"
    if op.get_context().as_sql:
        # ALTER TYPE ... ADD VALUE cannot run inside a transaction block, and
        # an offline script is one transaction. Emitted for review; the online
        # path below is what actually runs.
        op.execute(statement)
        return
    connection = op.get_bind()
    connection.execute(sa.text("COMMIT"))
    connection.execute(sa.text(statement))


def downgrade() -> None:
    # A value cannot be removed from a Postgres enum, and rebuilding the type
    # would mean rewriting every signal event row to drop readings a client
    # has already sent.
    pass
