"""Add historical teacher-to-class assignments.

Revision ID: 20260703_0005
Revises: 20260703_0004
Create Date: 2026-07-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260703_0005"
down_revision: str | Sequence[str] | None = "20260703_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

assignment_role_enum = postgresql.ENUM(
    "primary",
    "co_teacher",
    name="teacher_assignment_role",
    create_type=False,
)
assignment_source_enum = postgresql.ENUM(
    "manual",
    "roster_sync",
    name="teacher_assignment_source",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    assignment_role_enum.create(bind, checkfirst=True)
    assignment_source_enum.create(bind, checkfirst=True)

    op.create_table(
        "teacher_class_assignments",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "school_id",
            sa.Uuid(),
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "teacher_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "class_id",
            sa.Uuid(),
            sa.ForeignKey("classes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("role", assignment_role_enum, nullable=False),
        sa.Column(
            "source",
            assignment_source_enum,
            nullable=False,
            server_default="manual",
        ),
        sa.Column("source_reference", sa.String(length=255), nullable=True),
        sa.Column(
            "assigned_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "replaced_by_assignment_id",
            sa.Uuid(),
            sa.ForeignKey(
                "teacher_class_assignments.id",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.CheckConstraint(
            "removed_at IS NULL OR removed_at >= assigned_at",
            name="removed_after_assignment",
        ),
    )
    op.create_index(
        "ix_teacher_class_assignments_school_id",
        "teacher_class_assignments",
        ["school_id"],
    )
    op.create_index(
        "ix_teacher_class_assignments_teacher_active",
        "teacher_class_assignments",
        ["teacher_id", "removed_at"],
    )
    op.create_index(
        "ix_teacher_class_assignments_class_active",
        "teacher_class_assignments",
        ["class_id", "removed_at"],
    )
    op.create_index(
        "uq_teacher_class_assignments_active_pair",
        "teacher_class_assignments",
        ["teacher_id", "class_id"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.create_index(
        "uq_teacher_class_assignments_active_primary",
        "teacher_class_assignments",
        ["class_id"],
        unique=True,
        postgresql_where=sa.text(
            "role = 'primary' AND removed_at IS NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_teacher_class_assignments_active_primary",
        table_name="teacher_class_assignments",
    )
    op.drop_index(
        "uq_teacher_class_assignments_active_pair",
        table_name="teacher_class_assignments",
    )
    op.drop_index(
        "ix_teacher_class_assignments_class_active",
        table_name="teacher_class_assignments",
    )
    op.drop_index(
        "ix_teacher_class_assignments_teacher_active",
        table_name="teacher_class_assignments",
    )
    op.drop_index(
        "ix_teacher_class_assignments_school_id",
        table_name="teacher_class_assignments",
    )
    op.drop_table("teacher_class_assignments")
    assignment_source_enum.drop(op.get_bind(), checkfirst=True)
    assignment_role_enum.drop(op.get_bind(), checkfirst=True)
