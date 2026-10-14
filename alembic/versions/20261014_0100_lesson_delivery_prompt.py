"""Require activities, honest authorship, and lesson teaching aids in parsing."""

from alembic import op

revision = "20261014_0100"
down_revision = "20261013_0099"
branch_labels = None
depends_on = None

ADDITION = """
 Every text_variant includes keyPoints (two to four grounded highlights),
 keyTerms (term, definition, authoredBy), and equationCallouts where useful
 (equation, label, authoredBy). Do not fabricate a term or equation when none
 is relevant. Text you generate is authoredBy nevo; source quotations are
 person-authored, and transcripts remain records whose words are not rewritten.
 The segment body and text_variant body must be identical.
 An interactive_variant is an activity, never a comprehension question:
 include type activity, title, materials, ordered steps with id and instruction,
 and an actual observable outcome. Do not put options or an answer key in an
 activity; comprehension questions belong in comprehension_checkpoints.
 Identify optional natural module boundaries, never fixed segment counts.
 Return modules with title, segmentKeys, recap and preview. Use an empty
 modules list when a short lesson has no meaningful internal boundary.
"""


def upgrade():
    op.execute(f"""
        INSERT INTO ai_prompt_templates
            (service, name, version, system_template, user_template, required_variables, active)
        SELECT service, name, version + 1, system_template || $tpl${ADDITION}$tpl$,
               user_template, required_variables, false
        FROM ai_prompt_templates WHERE name = 'content_parse.default' AND active = true
    """)
    op.execute("UPDATE ai_prompt_templates SET active = false WHERE name = 'content_parse.default'")
    op.execute("""UPDATE ai_prompt_templates SET active = true
        WHERE name = 'content_parse.default' AND version =
        (SELECT max(version) FROM ai_prompt_templates WHERE name = 'content_parse.default')""")


def downgrade():
    op.execute(
        "DELETE FROM ai_prompt_templates WHERE name = 'content_parse.default' AND active = true"
    )
    op.execute("""UPDATE ai_prompt_templates SET active = true
        WHERE name = 'content_parse.default' AND version =
        (SELECT max(version) FROM ai_prompt_templates WHERE name = 'content_parse.default')""")
