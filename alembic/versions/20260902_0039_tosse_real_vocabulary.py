"""Match the lead vocabulary to the TOSSE landing page.

Revision ID: 20260902_0039
Revises: 20260902_0038
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260902_0039"
down_revision: str | Sequence[str] | None = "20260902_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The intent values were a placeholder guessed before SCRUM-117 was settled.
# Two of the three cards on the built page - "Schedule a walkthrough for my
# team" and "I'm interested, contact me this week" - had no matching value, so
# two thirds of submissions would have been rejected at the stand.
INTENTS = ("schedule_walkthrough", "contact_me")

# The dropdown offers Teacher and Parent. Without these both would have been
# recorded as "other", losing the distinction on the only lead list we get.
ROLES = ("teacher", "parent")


def upgrade() -> None:
    for value in INTENTS:
        op.execute(
            f"ALTER TYPE partner_inquiry_intent ADD VALUE IF NOT EXISTS '{value}'"
        )
    for value in ROLES:
        op.execute(f"ALTER TYPE partner_inquiry_role ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Postgres cannot drop a value from an enum type. Removing these would mean
    # rebuilding the type and rewriting every column that uses it, which is not
    # worth it for additive values that harm nothing by remaining.
    pass
