"""Teacher sign-off for questions and answer keys.

Revision ID: 20261025_0121
Revises: 20261024_0120
"""

from alembic import op

revision = "20261025_0121"
down_revision = "20261024_0120"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("kind_valid", "lesson_review_signoffs", type_="check")
    op.create_check_constraint(
        "kind_valid", "lesson_review_signoffs",
        "kind IN ('key_points', 'rewrites', 'guided_steps', 'checks')",
    )


def downgrade():
    op.execute("DELETE FROM lesson_review_signoffs WHERE kind = 'checks'")
    op.drop_constraint("kind_valid", "lesson_review_signoffs", type_="check")
    op.create_check_constraint(
        "kind_valid", "lesson_review_signoffs",
        "kind IN ('key_points', 'rewrites', 'guided_steps')",
    )
