"""Record typed safety findings and content-free decision hashes."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20261115_0143"
down_revision = "20261112_0142"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("content_safety_events", sa.Column("findings", JSONB(), nullable=True))
    op.add_column("content_safety_events", sa.Column("input_hash", sa.String(64), nullable=True))
    op.add_column("content_safety_events", sa.Column("prompt_hash", sa.String(64), nullable=True))
    op.add_column("content_safety_events", sa.Column("chunk_index", sa.Integer(), nullable=True))
    op.add_column("content_safety_events", sa.Column("chunk_count", sa.Integer(), nullable=True))
    op.add_column("content_safety_events", sa.Column("lesson_context", JSONB(), nullable=True))
    op.add_column("content_safety_events", sa.Column("review_material", sa.Text(), nullable=True))
    op.add_column(
        "content_safety_events",
        sa.Column("material_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("content_safety_events", sa.Column("review_label", sa.String(32), nullable=True))
    op.add_column(
        "content_safety_events",
        sa.Column(
            "reviewed_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
    )
    op.add_column(
        "content_safety_events", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "safety_review_access",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "event_id",
            sa.Uuid(),
            sa.ForeignKey("content_safety_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("safety_review_access")
    op.drop_column("content_safety_events", "reviewed_at")
    op.drop_column("content_safety_events", "reviewed_by")
    op.drop_column("content_safety_events", "review_label")
    op.drop_column("content_safety_events", "material_expires_at")
    op.drop_column("content_safety_events", "review_material")
    op.drop_column("content_safety_events", "prompt_hash")
    op.drop_column("content_safety_events", "chunk_count")
    op.drop_column("content_safety_events", "chunk_index")
    op.drop_column("content_safety_events", "lesson_context")
    op.drop_column("content_safety_events", "input_hash")
    op.drop_column("content_safety_events", "findings")
