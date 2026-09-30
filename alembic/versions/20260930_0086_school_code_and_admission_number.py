"""A four-character school code, and the child's own identifier. SCRUM-201, 202.

The school code is read out loud across a classroom and typed by a child, so it
is four characters from an alphabet with 0, O, 1 and I removed - both halves of
each confusable pair, so there is never a judgement call about what was meant.
Existing codes were eight hex characters and do not match, so they are
regenerated here. A school that had written its old code down will need the new
one, which is on the admin overview and in the teacher console header.

The admission number is the school's own Student ID. Unique on the pair
(school, number) and case insensitive, because Brightgate's 2024/001 and
Corona's 2024/001 are two different children and a school will write adm001 in
one file and ADM001 in the next meaning the same one.

Revision ID: 20260930_0086
Revises: 20260929_0085
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from nevo.domain.accounts.codes import SCHOOL_CODE_ALPHABET, new_school_code

revision: str = "20260930_0086"
down_revision: str | Sequence[str] | None = "20260929_0085"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("admission_number", sa.String(length=60), nullable=True))
    op.create_index(
        "uq_users_school_admission_number_ci",
        "users",
        ["school_id", sa.text("lower(admission_number)")],
        unique=True,
        postgresql_where=sa.text("admission_number IS NOT NULL"),
    )
    # Four characters is shorter than the column, but the column stays wide:
    # narrowing it would rewrite the table for no gain, and a school code has
    # never been length-validated in the database.
    if op.get_context().as_sql:
        # Regenerating reads and rewrites rows, which an offline script cannot.
        return
    _regenerate_school_codes(op.get_bind())


def _regenerate_school_codes(bind: sa.engine.Connection) -> None:
    """Give every school a code that matches the new alphabet.

    Retried per school on collision rather than pre-computing a unique set:
    with a million codes and a handful of schools a clash is very unlikely, and
    the unique constraint is what actually guarantees it either way.
    """

    pattern = f"^[{SCHOOL_CODE_ALPHABET}]{{4}}$"
    schools = (
        bind.execute(
            sa.text("SELECT id FROM schools WHERE school_code !~ :pattern"), {"pattern": pattern}
        )
        .scalars()
        .all()
    )
    taken = set(bind.execute(sa.text("SELECT school_code FROM schools")).scalars().all())
    for school_id in schools:
        for _ in range(50):
            code = new_school_code()
            if code not in taken:
                break
        else:  # pragma: no cover - a million codes and a handful of schools
            raise RuntimeError("Could not find a free school code")
        taken.add(code)
        bind.execute(
            sa.text("UPDATE schools SET school_code = :code WHERE id = :id"),
            {"code": code, "id": school_id},
        )


def downgrade() -> None:
    op.drop_index("uq_users_school_admission_number_ci", "users")
    op.drop_column("users", "admission_number")
