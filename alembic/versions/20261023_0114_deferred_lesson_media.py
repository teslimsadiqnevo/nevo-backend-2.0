"""Optional lesson media jobs with leased work and explicit approval."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20261023_0114"
down_revision = "20261023_0113"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "deferred_lesson_media",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column(
            "lesson_id", sa.Uuid, sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "segment_id",
            sa.Uuid,
            sa.ForeignKey("lesson_segments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by", sa.Uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("result", JSONB),
        sa.Column("failure_code", sa.String(60)),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("lease_token", sa.Uuid),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by", sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_by_name", sa.String(300)),
        sa.CheckConstraint("kind IN ('image', 'audio')", name="ck_deferred_media_kind"),
        sa.CheckConstraint(
            "status IN ('queued','processing','awaiting_review','approved','failed','stale')",
            name="ck_deferred_media_status",
        ),
        sa.UniqueConstraint("segment_id", "kind", name="uq_deferred_media_segment_kind"),
    )
    op.create_index(
        "ix_deferred_media_claim", "deferred_lesson_media", ["kind", "status", "lease_until"]
    )


def downgrade():
    op.drop_table("deferred_lesson_media")
