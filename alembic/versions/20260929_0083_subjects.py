"""Subjects on the class and on the teacher, and who teaches what. SCRUM-194.

Nevo had no idea what subject a class was taught or what subject a teacher
taught. A student was attached to a class and a teacher to a class, and nothing
else - which is why nothing could report a child's progress by subject.

Everything here references school_subjects and nothing references the canonical
list directly. A school's list holds a row per subject it uses however that
subject arrived, so pointing a school's "Maths" row at canonical Mathematics
later changes what the row resolves to and touches none of the mastery records
filed against it.

This also replaces classes.stated_subjects, the free-text list added on
24 September before this ticket existed. Its values are carried over rather
than dropped: each becomes a school subject, matched to a canonical one by
name where it matches.

Revision ID: 20260929_0083
Revises: 20260927_0082
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from nevo.domain.subjects.vocabulary import CANONICAL_SUBJECTS

revision: str = "20260929_0083"
down_revision: str | Sequence[str] | None = "20260927_0082"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    # Created once, here, and then referenced with create_type=False. Left to
    # the column definitions they are emitted again per table, which a real run
    # tolerates through checkfirst and an offline --sql script does not.
    sa.Enum("canonical", "school", name="subject_origin").create(bind, checkfirst=True)
    sa.Enum("pending", "kept", "merged", name="subject_review_state").create(bind, checkfirst=True)
    subject_origin = postgresql.ENUM(
        "canonical", "school", name="subject_origin", create_type=False
    )
    subject_review_state = postgresql.ENUM(
        "pending", "kept", "merged", name="subject_review_state", create_type=False
    )

    op.create_table(
        "canonical_subjects",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "school_subjects",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("normalised_name", sa.String(length=120), nullable=False),
        sa.Column("origin", subject_origin, nullable=False),
        sa.Column("canonical_subject_id", sa.Uuid(), nullable=True),
        sa.Column("review_state", subject_review_state, nullable=False, server_default="pending"),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["canonical_subject_id"], ["canonical_subjects.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("school_id", "normalised_name", name="uq_school_subjects_name"),
    )
    op.create_index("ix_school_subjects_school", "school_subjects", ["school_id"])
    op.create_index(
        "ix_school_subjects_review",
        "school_subjects",
        ["review_state"],
        postgresql_where=sa.text("origin = 'school'"),
    )
    for table, owner, owner_table in (
        ("class_subjects", "class_id", "classes"),
        ("teacher_subjects", "teacher_id", "users"),
    ):
        op.create_table(
            table,
            sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
            sa.Column(owner, sa.Uuid(), nullable=False),
            sa.Column("school_subject_id", sa.Uuid(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint([owner], [f"{owner_table}.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["school_subject_id"], ["school_subjects.id"], ondelete="RESTRICT"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(owner, "school_subject_id", name=f"uq_{table}"),
        )
        op.create_index(f"ix_{table}_subject", table, ["school_subject_id"])

    # An assignment becomes teacher plus subject plus class. Nullable, because
    # the rows that predate this have no subject to give them.
    op.add_column(
        "teacher_class_assignments", sa.Column("school_subject_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "fk_teacher_class_assignments_school_subject_id",
        "teacher_class_assignments",
        "school_subjects",
        ["school_subject_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    # Teacher and class was unique. That made the thing this ticket asks for
    # impossible: one teacher, one class, two subjects is two assignments.
    op.drop_index("uq_teacher_class_assignments_active_pair", "teacher_class_assignments")
    op.create_index(
        "uq_teacher_class_assignments_active_triple",
        "teacher_class_assignments",
        ["teacher_id", "class_id", "school_subject_id"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
        postgresql_nulls_not_distinct=True,
    )

    if not op.get_context().as_sql:
        # Seeding and the carry-over read rows back, which an offline script
        # cannot do. The schema change below is not conditional: leaving the
        # column behind offline would make the two paths disagree.
        _seed_canonical(bind)
        _carry_over_stated_subjects(bind)
    op.drop_column("classes", "stated_subjects")


def _seed_canonical(bind: sa.engine.Connection) -> None:
    bind.execute(
        sa.text(
            "INSERT INTO canonical_subjects (slug, display_name) VALUES (:slug, :name) "
            "ON CONFLICT (slug) DO NOTHING"
        ),
        [{"slug": slug, "name": name} for slug, name in CANONICAL_SUBJECTS],
    )


def _carry_over_stated_subjects(bind: sa.engine.Connection) -> None:
    """Keep what schools already typed, rather than making them type it again."""

    rows = bind.execute(
        sa.text(
            "SELECT id, school_id, stated_subjects FROM classes "
            "WHERE jsonb_array_length(COALESCE(stated_subjects, '[]'::jsonb)) > 0"
        )
    ).all()
    for class_id, school_id, stated in rows:
        for raw in stated or []:
            name = str(raw).strip()
            if not name:
                continue
            normalised = " ".join(name.split()).casefold()
            canonical = bind.execute(
                sa.text("SELECT id FROM canonical_subjects WHERE lower(display_name) = :name"),
                {"name": normalised},
            ).scalar()
            bind.execute(
                sa.text(
                    "INSERT INTO school_subjects "
                    "(school_id, name, normalised_name, origin, canonical_subject_id, "
                    " review_state) "
                    "VALUES (:school_id, :name, :normalised, :origin, :canonical, :state) "
                    "ON CONFLICT (school_id, normalised_name) DO NOTHING"
                ),
                {
                    "school_id": school_id,
                    "name": name,
                    "normalised": normalised,
                    "origin": "canonical" if canonical else "school",
                    "canonical": canonical,
                    "state": "merged" if canonical else "pending",
                },
            )
            subject_id = bind.execute(
                sa.text(
                    "SELECT id FROM school_subjects "
                    "WHERE school_id = :school_id AND normalised_name = :normalised"
                ),
                {"school_id": school_id, "normalised": normalised},
            ).scalar()
            bind.execute(
                sa.text(
                    "INSERT INTO class_subjects (class_id, school_subject_id) "
                    "VALUES (:class_id, :subject_id) ON CONFLICT DO NOTHING"
                ),
                {"class_id": class_id, "subject_id": subject_id},
            )


def downgrade() -> None:
    op.add_column(
        "classes",
        sa.Column(
            "stated_subjects",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.drop_index("uq_teacher_class_assignments_active_triple", "teacher_class_assignments")
    op.create_index(
        "uq_teacher_class_assignments_active_pair",
        "teacher_class_assignments",
        ["teacher_id", "class_id"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.drop_constraint(
        "fk_teacher_class_assignments_school_subject_id",
        "teacher_class_assignments",
        type_="foreignkey",
    )
    op.drop_column("teacher_class_assignments", "school_subject_id")
    for table in ("teacher_subjects", "class_subjects"):
        op.drop_index(f"ix_{table}_subject", table)
        op.drop_table(table)
    op.drop_index("ix_school_subjects_review", "school_subjects")
    op.drop_index("ix_school_subjects_school", "school_subjects")
    op.drop_table("school_subjects")
    op.drop_table("canonical_subjects")
    sa.Enum(name="subject_review_state").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="subject_origin").drop(op.get_bind(), checkfirst=True)
