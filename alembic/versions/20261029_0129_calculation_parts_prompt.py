"""Add reviewed calculation parts generation prompt and sign-off kind."""

from alembic import op

revision = "20261029_0129"
down_revision = "20261029_0128"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE lesson_review_signoffs DROP CONSTRAINT IF EXISTS kind_valid")
    op.execute("""ALTER TABLE lesson_review_signoffs ADD CONSTRAINT kind_valid
        CHECK (kind IN ('key_points', 'rewrites', 'guided_steps', 'checks', 'calculation_parts'))""")
    op.execute("""
        INSERT INTO ai_prompt_templates
            (service, name, version, system_template, user_template, required_variables, active)
        VALUES (
            'lesson_generation', 'calculation_parts.default', 1,
            'You split authored calculation steps into short, ordered reveal parts for slower pacing. '
            'Keep every mathematical claim and unit. Do not solve the step or reveal its answer. '
            'Do not invent smaller answerable steps. A step that cannot be divided meaningfully gets an empty parts list. '
            'Return only JSON: {{"steps":[{{"stepId":"...","parts":["...","..."]}}]}}. '
            'Use only stepIds supplied; each part is text, not a scored question.',
            'Lesson segment: {source_text}\nCalculation steps: {steps_json}',
            '["source_text", "steps_json"]'::jsonb, true
        )
    """)


def downgrade():
    op.execute("DELETE FROM ai_prompt_templates WHERE name = 'calculation_parts.default'")
    op.execute("ALTER TABLE lesson_review_signoffs DROP CONSTRAINT kind_valid")
    op.execute("""ALTER TABLE lesson_review_signoffs ADD CONSTRAINT kind_valid
        CHECK (kind IN ('key_points', 'rewrites', 'guided_steps', 'checks'))""")
