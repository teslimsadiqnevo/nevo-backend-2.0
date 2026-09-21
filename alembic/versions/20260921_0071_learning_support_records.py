"""What Nevo did for a child, dated, and who wrote what on the document.

Accommodations were worked out fresh whenever anybody asked, so the learning
support surface could say what is true today and never what changed in March
or why. And staff notes lived in a JSON blob on the export with nothing
guaranteeing an author or a time, so a document could not say which words were
the school's and which were Nevo's.

Neither table holds a score, an index, a rating or a forecast. They record
what the software did.

Revision ID: 20260921_0071
Revises: 20260921_0070
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260921_0071"
down_revision: str | Sequence[str] | None = "20260921_0070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOMMODATION = postgresql.ENUM(
    "reading",
    "attention",
    "numerical",
    name="accommodation_type",
    create_type=False,
)
ACTION = postgresql.ENUM(
    "added",
    "removed",
    name="accommodation_change_action",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    ACCOMMODATION.create(bind, checkfirst=True)
    ACTION.create(bind, checkfirst=True)

    op.create_table(
        "accommodation_changes",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("accommodation", ACCOMMODATION, nullable=False),
        sa.Column("action", ACTION, nullable=False),
        sa.Column("prompted_by", sa.String(length=120), nullable=False),
        sa.Column("observed_over_lessons", sa.Integer(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_accommodation_changes_student_time",
        "accommodation_changes",
        ["student_id", "occurred_at"],
    )

    op.create_table(
        "export_annotations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("export_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=False),
        sa.Column("author_name", sa.String(length=255), nullable=False),
        sa.Column("author_role", sa.String(length=40), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["export_id"], ["iep_exports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_export_annotations_export",
        "export_annotations",
        ["export_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_export_annotations_export", table_name="export_annotations")
    op.drop_table("export_annotations")
    op.drop_index("ix_accommodation_changes_student_time", table_name="accommodation_changes")
    op.drop_table("accommodation_changes")
    bind = op.get_bind()
    ACTION.drop(bind, checkfirst=True)
    ACCOMMODATION.drop(bind, checkfirst=True)
