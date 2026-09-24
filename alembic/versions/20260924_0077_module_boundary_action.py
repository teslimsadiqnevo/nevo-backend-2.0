"""Record what a child did at a module boundary, not only that they got there.

module_boundary_reached says a learner arrived at the end of a module.
Nothing said what they chose when the screen offered "Yes, continue" and
"Take a break first" - so the only place in the product where a child is
offered a break and answers recorded the offer and discarded the answer.

The client has been emitting it all along. It filters every event against a
copy of this enum before posting, because one unknown type refuses the whole
batch, so the event was collected on device and dropped at the door.

signal_event_type is a native Postgres enum, so a new value is added here
rather than by editing the Python enum alone.

Revision ID: 20260924_0077
Revises: 20260924_0076
Create Date: 2026-09-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260924_0077"
down_revision: str | Sequence[str] | None = "20260924_0076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_VALUE = "module_boundary_action"


def upgrade() -> None:
    # IF NOT EXISTS so a re-run is harmless. ALTER TYPE ... ADD VALUE cannot be
    # undone, which is why downgrade leaves it in place.
    op.execute(f"ALTER TYPE signal_event_type ADD VALUE IF NOT EXISTS '{NEW_VALUE}'")


def downgrade() -> None:
    # Postgres cannot remove a value from an enum. Leaving it is harmless:
    # nothing is required to emit one.
    pass
