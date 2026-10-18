"""Preserve legacy onboarding and separate personal reads from support acknowledgement."""

import sqlalchemy as sa

from alembic import op

revision = "20261018_0105"
down_revision = "20261018_0104"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "attention_flag_reads",
        sa.Column(
            "flag_id",
            sa.Uuid(),
            sa.ForeignKey("attention_flags.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_attention_flag_reads_user_seen", "attention_flag_reads", ["user_id", "seen_at"]
    )
    # A previous ordinary teacher click was personal reading, not support taking responsibility.
    op.execute("""INSERT INTO attention_flag_reads(flag_id, user_id, seen_at)
        SELECT f.id, f.acknowledged_by, f.acknowledged_at FROM attention_flags f
        JOIN users u ON u.id = f.acknowledged_by
        WHERE u.role = 'teacher' AND f.acknowledged_at IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM learning_support_grants g
            WHERE g.holder_user_id = u.id AND g.school_id = u.school_id
            AND g.granted_at <= f.acknowledged_at
            AND (g.revoked_at IS NULL OR g.revoked_at > f.acknowledged_at))
        ON CONFLICT DO NOTHING""")
    op.execute("""UPDATE attention_flags f SET acknowledged_at = NULL, acknowledged_by = NULL
        WHERE EXISTS (SELECT 1 FROM attention_flag_reads r
            WHERE r.flag_id = f.id AND r.user_id = f.acknowledged_by)""")
    # The old complete-baseline API had no per-module ledger. Do not infer
    # completion from account age or delivery defaults alone.
    op.execute("""WITH legacy AS (
        SELECT u.id FROM users u WHERE u.role = 'student' AND (
            EXISTS (SELECT 1 FROM lesson_sessions l WHERE l.student_id = u.id)
            OR (u.baseline_profile ? 'session_id'
                AND COALESCE(u.baseline_profile->>'feature_count', '0') ~ '^[1-9][0-9]*$'
                AND u.engine_config ? 'generatedFromBaselineAt'
                AND (NOT u.baseline_profile ? 'completed_modules'
                    OR u.baseline_profile->>'updated_at' < '2026-10-18T06:06:32'))
        )
    ) UPDATE users u SET baseline_profile = u.baseline_profile || jsonb_build_object(
        'completed_modules', (SELECT jsonb_agg(DISTINCT module) FROM (
            SELECT jsonb_array_elements_text(COALESCE(u.baseline_profile->'completed_modules', '[]'::jsonb)) module
            UNION SELECT unnest(ARRAY['grid_span','pattern_flanker','sentence_dot'])
        ) modules), 'legacy_onboarding_credit_reason', 'recorded_baseline_or_learning_activity')
        FROM legacy WHERE u.id = legacy.id""")


def downgrade():
    op.drop_table("attention_flag_reads")
