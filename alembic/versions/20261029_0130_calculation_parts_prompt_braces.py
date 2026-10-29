"""Escape JSON example braces for prompt rendering on upgraded databases."""

from alembic import op

revision = "20261029_0130"
down_revision = "20261029_0129"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE ai_prompt_templates
        SET system_template = replace(system_template,
            '{"steps":[{"stepId":"...","parts":["...","..."]}]}',
            '{{"steps":[{{"stepId":"...","parts":["...","..."]}}]}}')
        WHERE name = 'calculation_parts.default'
    """)


def downgrade():
    op.execute("""
        UPDATE ai_prompt_templates
        SET system_template = replace(system_template,
            '{{"steps":[{{"stepId":"...","parts":["...","..."]}}]}}',
            '{"steps":[{"stepId":"...","parts":["...","..."]}]}')
        WHERE name = 'calculation_parts.default'
    """)
