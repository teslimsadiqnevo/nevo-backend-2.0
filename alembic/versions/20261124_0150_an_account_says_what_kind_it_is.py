"""An account says what kind it is: school or individual.

/me, Phase 0. Every account until now belonged to a school, so nothing needed
to say so. The individual route (nevolearning.com/me) adds accounts that hold
no school, no class and no teacher, and the route guard needs one flag to read
rather than inferring the kind from a NULL school_id - a NULL that also
describes a broken roster row, and that matches no rows in any query that
compares against it, without failing.

Every existing row is a school account, so the default backfills them all and
the guard changes nothing for anybody already here. Nothing writes
'individual' until Phase 1 registration lands.

0150, 24 November 2026.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261124_0150"
down_revision = "20261123_0149"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "account_type",
            sa.String(length=20),
            nullable=False,
            server_default="school",
        ),
    )
    op.create_check_constraint(
        "account_type_kind",
        "users",
        "account_type in ('school', 'individual')",
    )


def downgrade() -> None:
    op.drop_constraint("account_type_kind", "users", type_="check")
    op.drop_column("users", "account_type")
