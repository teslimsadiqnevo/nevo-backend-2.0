"""Remove stored learning-style classifications, including historical columns."""

import sqlalchemy as sa

from alembic import op

revision = "20261018_0104"
down_revision = "20261018_0103"
branch_labels = None
depends_on = None

FIELDS = (
    "visual_spatial_preference",
    "auditory_preference",
    "reading_writing_preference",
    "interactive_kinesthetic_preference",
    "processing_channel_preference",
)


def upgrade():
    op.execute("""UPDATE ai_prompt_templates SET system_template = system_template ||
        E'\\n\\nFidelity requirements: retain EVERY numeric figure from the source in BOTH versions, '
        'including values in examples. Preserve equations and mathematical notation verbatim. '
        'Do not replace fractions by decimals or invent numbered lists. '
        'Simplified prose must be at least ten percent shorter; expanded prose must be at least '
        'ten percent longer without adding facts. All backslashes inside JSON string values '
        'must be escaped correctly. No literal unescaped line breaks inside JSON strings.'
        WHERE name = 'lesson_depth.default' AND active = true
        AND system_template NOT LIKE '%Fidelity requirements:%'""")
    op.execute("""UPDATE users SET baseline_profile = (baseline_profile - 'reading_wpm') ||
        '{"reading_wpm_source":"not_measured"}'::jsonb
        WHERE baseline_profile @> '{"reading_wpm": 120}'::jsonb
        AND NOT baseline_profile ? 'reading_wpm_source'""")
    op.execute("""UPDATE lesson_segments SET needs_review = true,
        review_reasons = COALESCE(review_reasons, '[]'::jsonb) ||
            '["depth_variant_review_required"]'::jsonb
        WHERE (depth_variants->'simplified'->>'reviewStatus' = 'pending' OR
               depth_variants->'expanded'->>'reviewStatus' = 'pending')
        AND NOT COALESCE(review_reasons, '[]'::jsonb) @> '["depth_variant_review_required"]'::jsonb""")
    # The old classifications are deliberately deleted, not archived elsewhere.
    op.execute(
        "DELETE FROM learner_profile_attention_flags WHERE dimension IN ("
        + ",".join("'" + name + "'" for name in FIELDS)
        + ")"
    )
    for table in ("learner_profiles", "learner_profile_history"):
        for name in FIELDS:
            op.drop_column(table, name + "_confidence")
            op.drop_column(table, name)
    # Strip classification keys recursively from existing structured export
    # evidence. The report text remains a reviewed document, not silently rewritten.
    op.execute("""CREATE FUNCTION pg_temp.nevo_without_styles(value jsonb) RETURNS jsonb
        LANGUAGE plpgsql AS $$
        DECLARE result jsonb; BEGIN
        IF jsonb_typeof(value) = 'object' THEN
          SELECT COALESCE(jsonb_object_agg(key, pg_temp.nevo_without_styles(val)), '{}'::jsonb)
          INTO result FROM jsonb_each(value) AS pairs(key,val)
          WHERE regexp_replace(lower(key), '_', '', 'g') NOT IN
          ('visualspatialpreference','auditorypreference','readingwritingpreference',
           'interactivekinestheticpreference','processingchannelpreference',
           'visualspatialpreferenceconfidence','auditorypreferenceconfidence',
           'readingwritingpreferenceconfidence','interactivekinestheticpreferenceconfidence',
           'processingchannelpreferenceconfidence','learningstyle','learningstyles',
           'preferredmodality','channelpreferences');
          RETURN result;
        ELSIF jsonb_typeof(value) = 'array' THEN
          SELECT COALESCE(jsonb_agg(pg_temp.nevo_without_styles(item)), '[]'::jsonb)
          INTO result FROM jsonb_array_elements(value) item;
          RETURN result;
        END IF; RETURN value; END $$""")
    for table, column in (
        ("iep_exports", "source_summary"),
        ("users", "baseline_profile"),
        ("users", "engine_config"),
        ("users", "preferences"),
        ("lesson_sessions", "delivery_state"),
    ):
        op.execute(
            f"UPDATE {table} SET {column} = pg_temp.nevo_without_styles({column}) "
            f"WHERE {column} IS DISTINCT FROM pg_temp.nevo_without_styles({column})"
        )


def downgrade():
    # Recreate empty compatibility fields only; deleted classifications cannot
    # and must not be reconstructed from events on rollback.
    for table in ("learner_profiles", "learner_profile_history"):
        for name in FIELDS:
            enum = (
                "processing_channel_preference"
                if name == "processing_channel_preference"
                else "channel_preference_strength"
            )
            op.add_column(table, sa.Column(name, sa.Enum(name=enum), nullable=True))
            op.add_column(
                table,
                sa.Column(
                    name + "_confidence",
                    sa.Enum(name="profile_confidence"),
                    nullable=False,
                    server_default="low",
                ),
            )
