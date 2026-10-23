"""Media withdrawal audit and lesson-wide professional review records."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20261023_0115"
down_revision = "20261023_0114"
branch_labels = depends_on = None


def upgrade():
    op.drop_constraint("ck_deferred_media_status", "deferred_lesson_media", type_="check")
    op.create_check_constraint(
        "ck_deferred_media_status",
        "deferred_lesson_media",
        "status IN ('queued','processing','awaiting_review','approved','failed','stale','withdrawn')",
    )
    op.add_column("deferred_lesson_media", sa.Column("withdrawn_at", sa.DateTime(timezone=True)))
    op.add_column(
        "deferred_lesson_media",
        sa.Column("withdrawn_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
    )
    op.add_column("deferred_lesson_media", sa.Column("withdrawn_by_name", sa.String(300)))
    # The held review branch may already have provisioned this table.
    if "lesson_review_signoffs" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "lesson_review_signoffs",
            sa.Column(
                "id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")
            ),
            sa.Column(
                "lesson_id",
                sa.Uuid(),
                sa.ForeignKey("lessons.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("approved_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("approved_by_name", sa.String(250), nullable=False),
            sa.Column(
                "approved_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("content_snapshot", JSONB, nullable=False),
            sa.Column("invalidated_at", sa.DateTime(timezone=True)),
            sa.CheckConstraint("kind IN ('key_points', 'rewrites')", name="kind_valid"),
        )
        op.create_index(
            "ix_lesson_review_signoffs_lesson_kind",
            "lesson_review_signoffs",
            ["lesson_id", "kind", "approved_at"],
        )


def downgrade():
    op.execute("UPDATE deferred_lesson_media SET status='stale' WHERE status='withdrawn'")
    op.drop_constraint("ck_deferred_media_status", "deferred_lesson_media", type_="check")
    op.create_check_constraint(
        "ck_deferred_media_status",
        "deferred_lesson_media",
        "status IN ('queued','processing','awaiting_review','approved','failed','stale')",
    )
    for name in ("withdrawn_by_name", "withdrawn_by", "withdrawn_at"):
        op.drop_column("deferred_lesson_media", name)
