"""Record each school DOB re-check as an append-only edit."""

from alembic import op
import sqlalchemy as sa

revision = "20261030_0131"
down_revision = "20261029_0130"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "age_check_edits",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("age_check_id", sa.Uuid(), sa.ForeignKey("age_checks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("actor_name", sa.String(250), nullable=False),
        sa.Column("previous_school_date_of_birth", sa.Date()),
        sa.Column("new_school_date_of_birth", sa.Date(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_age_check_edits_check_changed", "age_check_edits", ["age_check_id", "changed_at"])


def downgrade():
    op.drop_index("ix_age_check_edits_check_changed", table_name="age_check_edits")
    op.drop_table("age_check_edits")
