"""Durable media generation and provider-attempt accounting."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20261022_0112"
down_revision = "20261020_0111"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "media_usage_events",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("run_id", sa.Uuid, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("medium", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(40)),
        sa.Column("model", sa.String(100)),
        sa.Column("operation", sa.String(60)),
        sa.Column("attempt", sa.Integer),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("http_status", sa.Integer),
        sa.Column("request_id", sa.String(160)),
        sa.Column("charge_key", sa.String(200)),
        sa.Column("asset_path", sa.String(300)),
        sa.Column("usage", JSONB, nullable=False),
        sa.Column("pricing", JSONB, nullable=False),
        sa.Column("currency", sa.String(3)),
        sa.Column("estimated_cost", sa.Numeric(24, 10)),
        sa.Column("error_type", sa.String(100)),
    )
    op.create_index("ix_media_usage_time", "media_usage_events", ["occurred_at"])
    op.create_index("ix_media_usage_run", "media_usage_events", ["run_id"])
    op.create_index("ix_media_usage_charge", "media_usage_events", ["charge_key"])


def downgrade():
    op.drop_table("media_usage_events")
