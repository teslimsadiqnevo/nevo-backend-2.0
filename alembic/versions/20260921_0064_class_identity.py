"""A class knows its section, its school year, and what it is called twice.

Classes had a name and nothing else, so `jss 1a` and `JSS 1A ` were two
classes holding one class's children, and next year's JSS 1A would collide
with this year's. Both matter more now that class names come out of a school's
own uploaded file rather than being typed once by hand.

Revision ID: 20260921_0064
Revises: 20260921_0063
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260921_0064"
down_revision: str | Sequence[str] | None = "20260921_0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("classes", sa.Column("normalised_name", sa.String(length=255), nullable=True))
    op.add_column("classes", sa.Column("section", sa.String(length=20), nullable=True))
    op.add_column("classes", sa.Column("academic_session", sa.String(length=20), nullable=True))
    op.add_column("classes", sa.Column("capacity", sa.Integer(), nullable=True))

    # The existing rows get the same normalisation the application applies.
    op.execute(
        "UPDATE classes SET normalised_name = lower(btrim(regexp_replace(name, '\\s+', ' ', 'g')))"
    )
    # A class already in the database belongs to the school year it was made
    # in: September onwards is that year over the next, before it the previous
    # one over this. Guessing the current session instead would file a class
    # created last year under this year and collide it with its own successor.
    op.execute(
        """
        UPDATE classes
        SET academic_session = CASE
            WHEN EXTRACT(MONTH FROM created_at) >= 9
                THEN EXTRACT(YEAR FROM created_at)::text
                     || '/' || (EXTRACT(YEAR FROM created_at) + 1)::text
            ELSE (EXTRACT(YEAR FROM created_at) - 1)::text
                 || '/' || EXTRACT(YEAR FROM created_at)::text
        END
        """
    )
    # Section, where the name carries one: the trailing letter of "JSS 2A".
    op.execute(
        "UPDATE classes SET section = upper(substring(btrim(name) from '[0-9]\\s*([A-Za-z])$'))"
    )

    op.alter_column("classes", "normalised_name", nullable=False)
    op.alter_column("classes", "academic_session", nullable=False)

    _refuse_on_existing_duplicates()

    op.create_check_constraint(
        "class_capacity_positive",
        "classes",
        "capacity IS NULL OR capacity > 0",
    )
    # Unique among live classes only: an archived JSS 1A should not stop a
    # school re-creating one, and archiving is how a school corrects a typo.
    op.create_index(
        "uq_classes_school_session_name",
        "classes",
        ["school_id", "academic_session", "normalised_name"],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )


def _refuse_on_existing_duplicates() -> None:
    """Stop with the names, rather than with a unique-index violation.

    There are none in production today. If a database ever does hold two live
    JSS 1As, whoever runs this needs to know which school and which name so
    they can merge the rosters - not a constraint error naming an index.
    """

    if op.get_context().as_sql:
        return
    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT school_id, academic_session, normalised_name, count(*)"
                " FROM classes WHERE archived_at IS NULL"
                " GROUP BY 1, 2, 3 HAVING count(*) > 1"
            )
        )
        .all()
    )
    if duplicates:
        named = ", ".join(f"{row[2]} ({row[1]}) in school {row[0]}" for row in duplicates)
        raise RuntimeError(
            "These classes share a name within one school year and must be merged"
            f" or archived before this migration can run: {named}"
        )


def downgrade() -> None:
    op.drop_index("uq_classes_school_session_name", table_name="classes")
    op.drop_constraint("class_capacity_positive", "classes", type_="check")
    op.drop_column("classes", "capacity")
    op.drop_column("classes", "academic_session")
    op.drop_column("classes", "section")
    op.drop_column("classes", "normalised_name")
