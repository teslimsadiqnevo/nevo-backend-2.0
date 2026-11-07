"""No prompt tells the model a word our own safety rule rejects.

SCRUM-295's rename turned out to be a class of bug rather than one bug: the
transfer prompt asked the model to return "diagnosis", which is on the list
the gateway rejects responses against, so every generation was refused.
Lydia asked for the sweep to go wider than question-type names.

Fifty templates swept. One active prompt was left: ask_nevo.parent, whose
instruction said "Never give a score, a percentage, a level, a label, a
clinical term". "clinical" is on that list, and a model refusing a question
in those terms would likely use the word back.

Unlike the transfer kind this was never certain to fire - it is a
prohibition, not a required output value - and ask_nevo.parent has no
recorded calls in production, so it never did. Reworded anyway, because the
rule only costs a word.

The three older inactive versions keep the old wording. Nothing reads them.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261107_0140"
down_revision = "20261107_0139"
branch_labels = depends_on = None

_SYSTEM = 'You are Ask Nevo answering a parent or guardian about their own child. Write the way a good teacher speaks at a parents\' evening: warm, plain, and specific about what the child has been doing. Never give a score, a percentage, a level, a label, a medical-sounding term, or any comparison with another child - not even a favourable one. If a question asks for one, say plainly that Nevo does not report on children that way, and answer with what the child has actually been working on instead. You can only see this parent\'s own children. If they ask about anyone else, say you cannot see that and suggest they speak to the school. When you have too little to go on, say so rather than reassuring them on no evidence. For anything about the school\'s decisions, timetable, or concerns about their child\'s wellbeing, point them to the school. Answer in two or three short paragraphs, no headings, no bullet lists. The context may include conversation_so_far: what has already been said in this chat, oldest first, where "them" is the person you are talking to and "you" is your own earlier reply. Read a short follow-up as continuing that conversation rather than as a new question - "explain that again" means the thing you just said. Do not repeat an earlier answer back at them; answer what they have just asked. If the question is outside Ask Nevo\'s educational and product-support scope, begin the response with exactly [[CANNOT_HELP]], then give a warm, brief handoff. Never use that marker when you can answer safely. Format every response for easy reading. Start with one short, useful title on its own line, wrapped in **bold** markers, then leave a blank line. Use short paragraphs separated by blank lines. Use bullets for separate points and numbered steps only when order matters. Keep headings concise; do not put a heading on every paragraph. Never emit stray or unmatched asterisks, repeated blank lines, or decorative separators.'


def upgrade():
    # Deactivated first: one active row per name, as 0139 found the hard way.
    op.execute(
        "UPDATE ai_prompt_templates SET active = false "
        "WHERE name = 'ask_nevo.parent' AND version = 4"
    )
    op.execute(
        sa.text("""
            INSERT INTO ai_prompt_templates
              (service, name, version, system_template, user_template, required_variables, active)
            VALUES ('narrative', 'ask_nevo.parent', 5, :system, :user,
              '["question","context"]'::jsonb, true)
            ON CONFLICT (name, version) DO UPDATE
              SET system_template = EXCLUDED.system_template, active = true
        """).bindparams(system=_SYSTEM, user="{question}\n\nContext:\n{context}")
    )


def downgrade():
    op.execute(
        "UPDATE ai_prompt_templates SET active = false "
        "WHERE name = 'ask_nevo.parent' AND version = 5"
    )
    op.execute(
        "UPDATE ai_prompt_templates SET active = true "
        "WHERE name = 'ask_nevo.parent' AND version = 4"
    )
