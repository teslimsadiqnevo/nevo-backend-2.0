"""Record authoritative adaptation decisions separately from applied events."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20261018_0103"
down_revision = "20261018_0102"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""UPDATE lesson_segments AS segment SET concept_id = concept.id
        FROM concepts AS concept WHERE segment.concept_id IS NULL
        AND concept.id::text = segment.comprehension_checkpoints->0->>'conceptId'""")
    op.execute("""WITH evidence AS (
        SELECT DISTINCT student_id, event_data->>'moduleId' AS module
        FROM signal_events
        WHERE event_type = 'baseline_module_complete'
          AND event_data->>'moduleId' IN ('grid_span', 'pattern_flanker', 'sentence_dot')
        UNION
        SELECT student_id, 'domain_probe' FROM probe_responses
        WHERE correct IS NOT NULL GROUP BY student_id, school_subject_id HAVING count(*) >= 5
    ), completed AS (
        SELECT student_id, jsonb_agg(DISTINCT module) AS modules FROM evidence GROUP BY student_id
    ) UPDATE users SET baseline_profile = jsonb_set(
        baseline_profile, '{completed_modules}',
        COALESCE(baseline_profile->'completed_modules', '[]'::jsonb) || completed.modules
    ) FROM completed WHERE users.id = completed.student_id AND users.role = 'student'""")
    op.alter_column("probe_responses", "correct", existing_type=sa.Boolean(), nullable=True)
    op.create_table(
        "adaptation_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "student_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("lesson_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lesson_id", sa.Uuid(), nullable=False),
        sa.Column("segment_id", sa.String(120), nullable=True),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("trigger_signals", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="adaptation_decision_confidence"),
    )
    op.create_index(
        "ix_adaptation_decisions_student_session",
        "adaptation_decisions",
        ["student_id", "session_id"],
    )


def downgrade():
    op.alter_column("probe_responses", "correct", existing_type=sa.Boolean(), nullable=False)
    op.drop_table("adaptation_decisions")
