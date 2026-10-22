"""Content-free media accounting, deliberately not linked to a learner."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from nevo.db.base import Base

media_usage_events = sa.Table(
    "media_usage_events",
    Base.metadata,
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
    sa.Index("ix_media_usage_time", "occurred_at"),
    sa.Index("ix_media_usage_run", "run_id"),
    sa.Index("ix_media_usage_charge", "charge_key"),
)
