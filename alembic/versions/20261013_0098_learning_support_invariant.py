"""Guarantee one Learning Support holder per existing school.

Revision ID: 20261013_0098
Revises: 20261012_0095
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261013_0098"
down_revision: str | Sequence[str] | None = "20261012_0095"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        WITH missing AS (
            SELECT s.id AS school_id
            FROM schools s
            WHERE NOT EXISTS (
                SELECT 1
                FROM learning_support_grants lsg
                WHERE lsg.school_id = s.id
                  AND lsg.revoked_at IS NULL
            )
        ), chosen AS (
            SELECT m.school_id, picked.user_id
            FROM missing m
            CROSS JOIN LATERAL (
                SELECT a.user_id
                FROM admins a
                JOIN users u ON u.id = a.user_id
                WHERE a.school_id = m.school_id
                  AND u.status = 'active'
                ORDER BY (a.created_by_user_id IS NULL) DESC, u.created_at, a.id
                LIMIT 1
            ) picked
        )
        INSERT INTO learning_support_grants
            (school_id, holder_user_id, granted_by_user_id, granted_at)
        SELECT school_id, user_id, user_id, now()
        FROM chosen
        """
    )
    op.execute(
        """
        INSERT INTO admin_scope_assignments
            (admin_id, scope, granted_by_user_id, granted_at)
        SELECT a.id, 'senco', lsg.granted_by_user_id, lsg.granted_at
        FROM learning_support_grants lsg
        JOIN admins a ON a.user_id = lsg.holder_user_id
        WHERE lsg.revoked_at IS NULL
          AND NOT EXISTS (
              SELECT 1
              FROM admin_scope_assignments asa
              WHERE asa.admin_id = a.id
                AND asa.scope = 'senco'
                AND asa.revoked_at IS NULL
          )
        """
    )


def downgrade() -> None:
    # A data repair cannot distinguish repaired grants from later deliberate ones.
    pass
