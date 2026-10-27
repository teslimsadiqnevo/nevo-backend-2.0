"""Durable policy-version rechecks for stored lesson pictures.

Revision ID: 20261027_0124
Revises: 20261027_0123
"""

import sqlalchemy as sa
from alembic import op

revision = "20261027_0124"
down_revision = "20261027_0123"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "visual_safety_restamps",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("segment_id", sa.Uuid(), sa.ForeignKey("lesson_segments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("policy_version", sa.String(80), nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("failure_code", sa.String(60)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('queued','processing','passed','blocked','failed','stale')",
            name="ck_visual_restamp_status",
        ),
        sa.UniqueConstraint("segment_id", "policy_version", name="uq_visual_restamp_segment_policy"),
    )
    op.create_index("ix_visual_restamp_claim", "visual_safety_restamps", ["status", "lease_until"])


def downgrade():
    op.drop_index("ix_visual_restamp_claim", table_name="visual_safety_restamps")
    op.drop_table("visual_safety_restamps")
