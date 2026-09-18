"""Let the database hold the signals the client already emits.

The consolidation break asks a child how they are getting on and the answer
had nowhere to go: feeling_checkin was not a signal type, so the write was
refused and the reply discarded. break_suggested and break_taken said Nevo
offered a break and the child accepted; nothing said how long it lasted, which
is the part that tells you whether it helped.

signal_event_type is a native Postgres enum, so new values are added here
rather than by editing the Python enum alone.

Revision ID: 20260918_0060
Revises: 20260917_0059
Create Date: 2026-09-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260918_0060"
down_revision: str | Sequence[str] | None = "20260917_0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_VALUES = (
    "break_start",
    "break_end",
    "feeling_checkin",
    "module_boundary_reached",
)


def upgrade() -> None:
    # IF NOT EXISTS so a re-run is harmless. ALTER TYPE ... ADD VALUE cannot be
    # undone, which is why downgrade leaves them in place.
    for value in NEW_VALUES:
        op.execute(f"ALTER TYPE signal_event_type ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Postgres cannot remove a value from an enum. Leaving them is harmless:
    # nothing is required to emit one.
    pass
