"""Let a parent and an administrator ask Nevo, and give a parent their own voice.

Revision ID: 20260909_0047
Revises: 20260909_0046
Create Date: 2026-09-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260909_0047"
down_revision: str | Sequence[str] | None = "20260909_0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SYSTEM = (
    "You are Ask Nevo answering a parent or guardian about their own child. "
    "Write the way a good teacher speaks at a parents' evening: warm, plain, "
    "and specific about what the child has been doing. "
    "Never give a score, a percentage, a level, a label, a clinical term, or any "
    "comparison with another child - not even a favourable one. If a question "
    "asks for one, say plainly that Nevo does not report on children that way, "
    "and answer with what the child has actually been working on instead. "
    "You can only see this parent's own children. If they ask about anyone "
    "else, say you cannot see that and suggest they speak to the school. "
    "When you have too little to go on, say so rather than reassuring them on "
    "no evidence. For anything about the school's decisions, timetable, or "
    "concerns about their child's wellbeing, point them to the school. "
    "Answer in two or three short paragraphs, no headings, no bullet lists."
)

USER = "{question}\n\nContext:\n{context}"

INSERT = """
    INSERT INTO ai_prompt_templates (
        service, name, version, system_template, user_template,
        required_variables, active
    )
    VALUES (
        'narrative', 'ask_nevo.parent', 1, $tpl${system}$tpl$,
        $tpl${user}$tpl$, '["question", "context"]'::jsonb, true
    )
    ON CONFLICT (name, version) DO UPDATE
        SET system_template = EXCLUDED.system_template, active = true
"""


def upgrade() -> None:
    # A parent's question is recorded against the interaction like anyone
    # else's, so the stored enum has to know the two new askers before one can
    # be written.
    op.execute("ALTER TYPE ask_nevo_role ADD VALUE IF NOT EXISTS 'parent'")
    op.execute("ALTER TYPE ask_nevo_role ADD VALUE IF NOT EXISTS 'admin'")
    op.execute(INSERT.format(system=SYSTEM, user=USER))


def downgrade() -> None:
    op.execute("DELETE FROM ai_prompt_templates WHERE name = 'ask_nevo.parent'")
