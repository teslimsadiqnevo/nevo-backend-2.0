"""Track when an attention flag's evidence no longer holds.

Revision ID: 20261027_0123
Revises: 20261027_0122
"""

import sqlalchemy as sa
from alembic import op

revision = "20261027_0123"
down_revision = "20261027_0122"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "attention_flags", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.drop_index("ix_attention_flags_open_student", table_name="attention_flags")
    op.create_index(
        "ix_attention_flags_open_student", "attention_flags", ["student_id"],
        postgresql_where=sa.text("resolved_at IS NULL"),
    )


def downgrade():
    op.drop_index("ix_attention_flags_open_student", table_name="attention_flags")
    op.create_index(
        "ix_attention_flags_open_student", "attention_flags", ["student_id"],
        postgresql_where=sa.text("acknowledged_at IS NULL"),
    )
    op.drop_column("attention_flags", "resolved_at")
