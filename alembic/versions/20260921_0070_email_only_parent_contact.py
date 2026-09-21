"""A parent is reached by email, and nothing else.

Ruled on 20 September. You cannot collect personal data you have no use for:
four hundred parents' phone numbers nothing ever sends to are four hundred
pieces of personal data with no lawful purpose, sitting in a database that has
to be protected, purged and accounted for in the Data Sharing Agreement.

Deliverability was the argument for keeping SMS, and the written consent route
answers it better: a parent who does not answer email gets a paper form in
their child's bag.

No row in production uses SMS, so this drops the value rather than leaving a
door nothing walks through. A database that still accepts 'sms' is a database
that will hold one again.

Revision ID: 20260921_0070
Revises: 20260921_0069
Create Date: 2026-09-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260921_0070"
down_revision: str | Sequence[str] | None = "20260921_0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    ("parent_links", "contact_method"),
    ("consent_notification_outbox", "contact_method"),
)


def upgrade() -> None:
    if op.get_context().as_sql:
        op.execute("-- parent contact method is rebuilt against a live database")
        return
    bind = op.get_bind()
    remaining = bind.exec_driver_sql(
        "SELECT count(*) FROM parent_links WHERE contact_method = 'sms'"
    ).scalar()
    if remaining:
        # Stop with the count rather than silently deleting somebody's only
        # route to a parent. Whoever runs this decides what happens to them.
        raise RuntimeError(
            f"{remaining} parent links are still contacted by SMS. Move them to "
            "email, or delete them, before this migration can run."
        )
    op.execute("ALTER TYPE parent_contact_method RENAME TO parent_contact_method_old")
    op.execute("CREATE TYPE parent_contact_method AS ENUM ('email')")
    for table, column in TABLES:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE parent_contact_method"
            f" USING {column}::text::parent_contact_method"
        )
    op.execute("DROP TYPE parent_contact_method_old")


def downgrade() -> None:
    if op.get_context().as_sql:
        return
    op.execute("ALTER TYPE parent_contact_method RENAME TO parent_contact_method_old")
    op.execute("CREATE TYPE parent_contact_method AS ENUM ('email', 'sms')")
    for table, column in TABLES:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE parent_contact_method"
            f" USING {column}::text::parent_contact_method"
        )
    op.execute("DROP TYPE parent_contact_method_old")
