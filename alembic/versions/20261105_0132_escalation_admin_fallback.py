"""Keep concerns reachable when a school has no Learning Support holder."""

import sqlalchemy as sa

from alembic import op

revision = "20261105_0132"
down_revision = "20261030_0131"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("escalations", sa.Column(
        "routed_to", sa.String(32), nullable=False,
        server_default="learning_support",
    ))
    op.add_column("escalations", sa.Column(
        "recipient_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")
    ))
    op.add_column("escalations", sa.Column("received_at", sa.DateTime(timezone=True)))
    op.create_index("ix_escalations_recipient", "escalations", ["recipient_user_id"])
    op.execute("""
        WITH fallback AS (
            SELECT schools.id AS school_id,
                   (SELECT users.id
                    FROM admins JOIN users ON users.id = admins.user_id
                    WHERE admins.school_id = schools.id
                      AND users.school_id = schools.id
                      AND users.status = 'active'
                    ORDER BY (admins.access_level = 'senior') DESC,
                             admins.created_at, users.id
                    LIMIT 1) AS admin_id
            FROM schools
            WHERE NOT EXISTS (
                SELECT 1 FROM learning_support_grants grants
                JOIN users holders ON holders.id = grants.holder_user_id
                WHERE grants.school_id = schools.id
                  AND grants.revoked_at IS NULL
                  AND holders.status = 'active'
                  AND holders.school_id = schools.id
                  AND holders.role IN ('teacher', 'other_admin', 'senco_admin')
            )
        )
        UPDATE escalations concern
        SET routed_to = 'school_admin',
            recipient_user_id = fallback.admin_id
        FROM users child JOIN fallback ON fallback.school_id = child.school_id
        WHERE concern.student_id = child.id AND fallback.admin_id IS NOT NULL
    """)


def downgrade():
    op.drop_index("ix_escalations_recipient", table_name="escalations")
    op.drop_column("escalations", "received_at")
    op.drop_column("escalations", "recipient_user_id")
    op.drop_column("escalations", "routed_to")
