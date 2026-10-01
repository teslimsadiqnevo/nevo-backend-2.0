"""The student console's contract gaps. Asks B3-B5, B12-B20, B31, B34, B35.

Two things need the database.

Fourteen new signal event types, because ``signal_event_type`` is a native
Postgres enum and a type the database will not accept is a type the client
drops at the door - which is where the media failures, the system waits, the
baseline lifecycle and every hint, step-up and guided question have been going.

And a column for the name a child chooses for themselves, which the screen
that asks "What should we call you?" had nowhere to put. Its own column rather
than overwriting the roster name: a nickname is not a correction to a school's
record of a child.

Revision ID: 20261001_0088
Revises: 20260930_0087
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261001_0088"
down_revision = "20260930_0087"
branch_labels = None
depends_on = None

#: Added in this order so the enum reads in the order a session produces them.
NEW_EVENT_TYPES = (
    "media_load_failed",
    "system_busy",
    "tap_blocked",
    "session_context",
    "baseline_module_start",
    "baseline_module_complete",
    "baseline_submitted",
    "hint_offered",
    "hint_used",
    "step_up_offered",
    "step_up_accepted",
    "step_up_declined",
    "guided_question_shown",
    "guided_question_answered",
)


def upgrade() -> None:
    op.add_column("users", sa.Column("preferred_name", sa.String(length=60), nullable=True))
    if op.get_context().as_sql:
        # ALTER TYPE ... ADD VALUE cannot run inside a transaction block, and
        # an offline script is one transaction. Emitted for review; the online
        # path below is what actually runs.
        for value in NEW_EVENT_TYPES:
            op.execute(f"ALTER TYPE signal_event_type ADD VALUE IF NOT EXISTS '{value}'")
        return
    connection = op.get_bind()
    connection.execute(sa.text("COMMIT"))
    for value in NEW_EVENT_TYPES:
        connection.execute(
            sa.text(f"ALTER TYPE signal_event_type ADD VALUE IF NOT EXISTS '{value}'")
        )


def downgrade() -> None:
    # A value cannot be removed from a Postgres enum, and rebuilding the type
    # would mean rewriting every signal event row to drop readings a client
    # has already sent. The column goes; the enum values stay.
    op.drop_column("users", "preferred_name")
