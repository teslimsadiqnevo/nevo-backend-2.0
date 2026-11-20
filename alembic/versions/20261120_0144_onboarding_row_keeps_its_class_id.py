"""An onboarding row remembers which class it joined, by id.

The attachment between an uploaded roster row and a live class was the
class's folded name. The name is what a school types and the name is what
they change, so a class renamed between confirming an import and activating
it stopped matching: activation created a second class under the file's old
spelling, and the rest of the roster landed there. One class, silently split
in two, and nobody notices until a register is half empty.

This adds the id, backfills it for every row that can still be matched
unambiguously, and reports the classes that were already split so they can
be merged by hand - which is a decision about children's registers, not
something a migration should take.

T18, 20 November.
"""

from alembic import op
import sqlalchemy as sa

revision = "20261120_0144"
down_revision = "20261115_0143"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "onboarding_rows",
        sa.Column("class_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_onboarding_rows_class_id",
        "onboarding_rows",
        "classes",
        ["class_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_onboarding_rows_class_id",
        "onboarding_rows",
        ["class_id"],
    )

    # Backfill only where the folded name still identifies exactly one live
    # class in that school and session. A row whose name matches two classes
    # is precisely the damage this fixes, and guessing which half of a split
    # register a child belongs to is not a migration's decision.
    op.execute(
        """
        WITH candidate AS (
            SELECT r.id AS row_id,
                   MIN(c.id::text)::uuid AS class_id,
                   COUNT(*) AS matches
            FROM onboarding_rows r
            JOIN school_onboardings o ON o.id = r.onboarding_id
            JOIN classes c
              ON c.school_id = o.school_id
             AND c.normalised_name = r.normalised_class_name
             AND c.archived_at IS NULL
            WHERE r.normalised_class_name IS NOT NULL
            GROUP BY r.id
        )
        UPDATE onboarding_rows AS r
        SET class_id = candidate.class_id
        FROM candidate
        WHERE candidate.row_id = r.id
          AND candidate.matches = 1
        """
    )

    # Say out loud what could not be backfilled, so it is a known list rather
    # than a surprise later. Reported, never merged: merging two registers is
    # a school's call.
    rows = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT o.school_id,
                       r.normalised_class_name,
                       COUNT(DISTINCT r.id) AS affected_rows
                FROM onboarding_rows r
                JOIN school_onboardings o ON o.id = r.onboarding_id
                JOIN classes c
                  ON c.school_id = o.school_id
                 AND c.normalised_name = r.normalised_class_name
                 AND c.archived_at IS NULL
                WHERE r.normalised_class_name IS NOT NULL
                  AND r.class_id IS NULL
                GROUP BY o.school_id, r.normalised_class_name
                HAVING COUNT(DISTINCT c.id) > 1
                """
            )
        )
        .fetchall()
    )
    for school_id, name, affected in rows:
        print(
            f"[T18] school {school_id}: '{name}' matches more than one live "
            f"class; {affected} onboarding row(s) left unpinned for a human "
            f"to resolve."
        )
    if not rows:
        print("[T18] no split classes found; every row pinned or unambiguous.")


def downgrade() -> None:
    op.drop_index("ix_onboarding_rows_class_id", table_name="onboarding_rows")
    op.drop_constraint(
        "fk_onboarding_rows_class_id", "onboarding_rows", type_="foreignkey"
    )
    op.drop_column("onboarding_rows", "class_id")
