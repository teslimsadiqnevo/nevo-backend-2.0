"""A learner says what they expect; the waitlist and enquiries are kept.

/me, Phase 6.

me_check_predictions: before a lesson's check, the learner names the level
(knowledge, application, analysis) they expect to reach. The outcome is not
stored - it is read from the attempts made after the prediction, which are
already the record - so it can never disagree with them. Ruling D1.

me_contact_requests: the waitlist and the enquiry form. Neither creates an
account and neither touches the tier model.

0154, 24 November 2026.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261124_0154"
down_revision = "20261124_0153"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "me_check_predictions",
        sa.Column(
            "id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "learner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lesson_id", sa.Uuid(), sa.ForeignKey("lessons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("predicted_level", sa.String(20), nullable=False),
        sa.Column("predicted_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "predicted_level IN ('knowledge', 'application', 'analysis')",
            name="predicted_level_known",
        ),
    )
    op.create_index(
        "ix_me_check_predictions_learner_lesson",
        "me_check_predictions",
        ["learner_id", "lesson_id", "predicted_at"],
    )
    op.create_table(
        "me_contact_requests",
        sa.Column(
            "id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("who", sa.String(40), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "learner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('waitlist', 'enquiry')", name="kind_known"),
    )
    op.create_index(
        "ix_me_contact_requests_email_created", "me_contact_requests", ["email", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_me_contact_requests_email_created", table_name="me_contact_requests")
    op.drop_table("me_contact_requests")
    op.drop_index("ix_me_check_predictions_learner_lesson", table_name="me_check_predictions")
    op.drop_table("me_check_predictions")
