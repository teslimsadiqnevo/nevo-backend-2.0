"""A teacher can settle the key points Nevo was unsure of.

The product told a teacher parts of a lesson needed review and then offered no
way to perform one, so no lesson could be assigned. A review is per key point,
so a key point has to be a row: the text as extracted, the text the teacher
made of it, the source it was drawn from, and who settled it when.

Existing lessons are backfilled from their segments' text variants, with the
same grounding measure the pipeline now applies, so a library parsed before
today opens with the same review state it would have had.

Revision ID: 20260921_0063
Revises: 20260918_0062
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from nevo.content_parsing.key_points import confidence as key_point_confidence
from nevo.domain.intelligence.vocabulary import KeyPointConfidence

revision: str = "20260921_0063"
down_revision: str | Sequence[str] | None = "20260918_0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONFIDENCE = postgresql.ENUM(
    "high",
    "medium",
    "low",
    name="key_point_confidence",
    create_type=False,
)
REVIEW_STATE = postgresql.ENUM(
    "settled",
    "unsure",
    "accepted",
    "amended",
    "removed",
    name="key_point_review_state",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    CONFIDENCE.create(bind, checkfirst=True)
    REVIEW_STATE.create(bind, checkfirst=True)

    op.create_table(
        "lesson_key_points",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("lesson_id", sa.Uuid(), nullable=False),
        sa.Column("segment_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("amended_text", sa.Text(), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("confidence", CONFIDENCE, nullable=False),
        sa.Column("review_state", REVIEW_STATE, nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("position >= 0", name="lesson_key_point_position_non_negative"),
        sa.CheckConstraint(
            "(review_state IN ('settled', 'unsure')"
            " AND resolved_at IS NULL AND resolved_by IS NULL)"
            " OR (review_state IN ('accepted', 'amended', 'removed')"
            " AND resolved_at IS NOT NULL)",
            name="lesson_key_point_resolution_matches_state",
        ),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["segment_id"], ["lesson_segments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_lesson_key_points_lesson_position",
        "lesson_key_points",
        ["lesson_id", "segment_id", "position"],
        unique=True,
    )
    op.create_index(
        "ix_lesson_key_points_outstanding",
        "lesson_key_points",
        ["lesson_id"],
        postgresql_where=sa.text("review_state = 'unsure'"),
    )

    _backfill(bind)


def _backfill(bind: sa.engine.Connection) -> None:
    """Give lessons already in the library the review state they would have had.

    Done in Python rather than SQL because the grounding measure is the
    pipeline's, and a second implementation in SQL would be a second answer.
    That means it needs a live database: generating the migration as a script
    (``--sql``) has nothing to read, so it writes the schema and leaves the
    backfill to a real run.
    """

    if op.get_context().as_sql:
        op.execute("-- key point backfill runs against a live database, not in --sql mode")
        return
    segments = bind.execute(
        sa.text(
            "SELECT id, lesson_id, body, text_variant FROM lesson_segments"
            " WHERE text_variant ? 'keyPoints'"
        )
    ).all()
    rows = []
    for segment_id, lesson_id, body, variant in segments:
        points = (variant or {}).get("keyPoints")
        if not isinstance(points, list):
            continue
        for position, raw in enumerate(points):
            text = str(raw).strip()
            if not text:
                continue
            confidence = key_point_confidence(text, body or "")
            rows.append(
                {
                    "lesson_id": lesson_id,
                    "segment_id": segment_id,
                    "position": position,
                    "extracted_text": text,
                    "source_text": body or "",
                    "confidence": confidence.value,
                    "review_state": (
                        "unsure" if confidence is KeyPointConfidence.LOW else "settled"
                    ),
                }
            )
    if not rows:
        return
    bind.execute(
        sa.text(
            "INSERT INTO lesson_key_points"
            " (lesson_id, segment_id, position, extracted_text, source_text,"
            "  confidence, review_state)"
            " VALUES (:lesson_id, :segment_id, :position, :extracted_text, :source_text,"
            "  :confidence, :review_state)"
        ),
        rows,
    )


def downgrade() -> None:
    op.drop_index("ix_lesson_key_points_outstanding", table_name="lesson_key_points")
    op.drop_index("ix_lesson_key_points_lesson_position", table_name="lesson_key_points")
    op.drop_table("lesson_key_points")
    bind = op.get_bind()
    REVIEW_STATE.drop(bind, checkfirst=True)
    CONFIDENCE.drop(bind, checkfirst=True)
