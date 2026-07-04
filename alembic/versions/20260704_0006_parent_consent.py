"""Add parent accounts and consent collection.

Revision ID: 20260704_0006
Revises: 20260703_0005
Create Date: 2026-07-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260704_0006"
down_revision: str | Sequence[str] | None = "20260703_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

confirmation_source_enum = postgresql.ENUM(
    "school",
    "parent",
    name="consent_confirmation_source",
    create_type=False,
)
parent_contact_method_enum = postgresql.ENUM(
    "email",
    "sms",
    name="parent_contact_method",
    create_type=False,
)
delivery_status_enum = postgresql.ENUM(
    "queued",
    "sent",
    "failed",
    name="consent_delivery_status",
    create_type=False,
)
consent_type_enum = postgresql.ENUM(
    "data_processing",
    "camera",
    "offline_storage",
    name="consent_type",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'parent_guardian'")
    confirmation_source_enum.create(bind, checkfirst=True)
    parent_contact_method_enum.create(bind, checkfirst=True)
    delivery_status_enum.create(bind, checkfirst=True)

    op.drop_constraint(
        op.f("ck_consent_records_confirmation_fields_match_status"),
        "consent_records",
        type_="check",
    )
    op.add_column(
        "consent_records",
        sa.Column("confirmed_by_parent_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "consent_records",
        sa.Column(
            "confirmation_source",
            confirmation_source_enum,
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_consent_records_confirmed_by_parent_id_users",
        "consent_records",
        "users",
        ["confirmed_by_parent_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_consent_records_confirmed_by_parent_id",
        "consent_records",
        ["confirmed_by_parent_id"],
    )
    op.execute(
        """
        UPDATE consent_records
        SET confirmation_source = 'school'
        WHERE status = 'confirmed'
        """
    )
    op.create_check_constraint(
        "confirmation_fields_match_status",
        "consent_records",
        """
        (
            status = 'pending'
            AND confirmation_source IS NULL
            AND confirmed_by_admin_id IS NULL
            AND confirmed_by_parent_id IS NULL
            AND confirmed_via IS NULL
            AND confirmed_at IS NULL
        ) OR (
            status = 'confirmed'
            AND confirmed_via IS NOT NULL
            AND confirmed_at IS NOT NULL
            AND (
                (
                    confirmation_source = 'school'
                    AND confirmed_by_admin_id IS NOT NULL
                    AND confirmed_by_parent_id IS NULL
                ) OR (
                    confirmation_source = 'parent'
                    AND confirmed_by_parent_id IS NOT NULL
                    AND confirmed_by_admin_id IS NULL
                )
            )
        )
        """,
    )

    op.create_table(
        "parent_links",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "school_id",
            sa.Uuid(),
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "parent_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("parent_name", sa.String(length=255), nullable=False),
        sa.Column("parent_contact", sa.String(length=255), nullable=False),
        sa.Column(
            "contact_method",
            parent_contact_method_enum,
            nullable=False,
        ),
        sa.Column(
            "account_created",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "student_id",
            "parent_contact",
            "contact_method",
            name="uq_parent_links_student_contact_method",
        ),
        sa.CheckConstraint(
            "account_created = (parent_id IS NOT NULL)",
            name="account_created_matches_parent",
        ),
    )
    op.create_index("ix_parent_links_school_id", "parent_links", ["school_id"])
    op.create_index("ix_parent_links_student_id", "parent_links", ["student_id"])
    op.create_index("ix_parent_links_parent_id", "parent_links", ["parent_id"])

    op.create_table(
        "consent_invitations",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "parent_link_id",
            sa.Uuid(),
            sa.ForeignKey("parent_links.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "school_id",
            sa.Uuid(),
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "requested_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "token_digest",
            name="uq_consent_invitations_token_digest",
        ),
        sa.CheckConstraint(
            "NOT (accepted_at IS NOT NULL AND revoked_at IS NOT NULL)",
            name="not_accepted_and_revoked",
        ),
    )
    op.create_index(
        "ix_consent_invitations_parent_link_id",
        "consent_invitations",
        ["parent_link_id"],
    )
    op.create_index(
        "ix_consent_invitations_school_id",
        "consent_invitations",
        ["school_id"],
    )
    op.create_index(
        "ix_consent_invitations_student_id",
        "consent_invitations",
        ["student_id"],
    )

    op.create_table(
        "consent_invitation_items",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "invitation_id",
            sa.Uuid(),
            sa.ForeignKey("consent_invitations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("consent_type", consent_type_enum, nullable=False),
        sa.UniqueConstraint(
            "invitation_id",
            "consent_type",
            name="uq_consent_invitation_items_invitation_type",
        ),
    )
    op.create_index(
        "ix_consent_invitation_items_invitation_id",
        "consent_invitation_items",
        ["invitation_id"],
    )

    op.create_table(
        "consent_notification_outbox",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "invitation_id",
            sa.Uuid(),
            sa.ForeignKey("consent_invitations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "contact_method",
            parent_contact_method_enum,
            nullable=False,
        ),
        sa.Column("destination", sa.String(length=255), nullable=False),
        sa.Column("consent_url", sa.Text(), nullable=False),
        sa.Column(
            "status",
            delivery_status_enum,
            nullable=False,
            server_default="queued",
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "invitation_id",
            name="uq_consent_notification_outbox_invitation_id",
        ),
        sa.CheckConstraint(
            "(status = 'sent') = (sent_at IS NOT NULL)",
            name="sent_status_matches_timestamp",
        ),
    )

    op.execute(
        """
        CREATE FUNCTION create_pending_consent_for_roster_student()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.role = 'student' AND NEW.auth_method = 'sso' THEN
                INSERT INTO consent_records (
                    subject_user_id,
                    consent_type,
                    status
                )
                VALUES (
                    NEW.id,
                    'data_processing',
                    'pending'
                )
                ON CONFLICT (subject_user_id, consent_type) DO NOTHING;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_users_roster_student_pending_consent
        AFTER INSERT ON users
        FOR EACH ROW
        EXECUTE FUNCTION create_pending_consent_for_roster_student();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_users_roster_student_pending_consent ON users"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS create_pending_consent_for_roster_student()"
    )
    op.drop_table("consent_notification_outbox")
    op.drop_index(
        "ix_consent_invitation_items_invitation_id",
        table_name="consent_invitation_items",
    )
    op.drop_table("consent_invitation_items")
    op.drop_index(
        "ix_consent_invitations_student_id",
        table_name="consent_invitations",
    )
    op.drop_index(
        "ix_consent_invitations_school_id",
        table_name="consent_invitations",
    )
    op.drop_index(
        "ix_consent_invitations_parent_link_id",
        table_name="consent_invitations",
    )
    op.drop_table("consent_invitations")
    op.drop_index("ix_parent_links_parent_id", table_name="parent_links")
    op.drop_index("ix_parent_links_student_id", table_name="parent_links")
    op.drop_index("ix_parent_links_school_id", table_name="parent_links")
    op.drop_table("parent_links")

    op.drop_constraint(
        op.f("ck_consent_records_confirmation_fields_match_status"),
        "consent_records",
        type_="check",
    )
    op.drop_index(
        "ix_consent_records_confirmed_by_parent_id",
        table_name="consent_records",
    )
    op.drop_constraint(
        op.f("fk_consent_records_confirmed_by_parent_id_users"),
        "consent_records",
        type_="foreignkey",
    )
    op.drop_column("consent_records", "confirmation_source")
    op.drop_column("consent_records", "confirmed_by_parent_id")
    op.create_check_constraint(
        "confirmation_fields_match_status",
        "consent_records",
        """
        (status = 'confirmed') = (
            confirmed_by_admin_id IS NOT NULL
            AND confirmed_via IS NOT NULL
            AND confirmed_at IS NOT NULL
        )
        """,
    )
    delivery_status_enum.drop(op.get_bind(), checkfirst=True)
    parent_contact_method_enum.drop(op.get_bind(), checkfirst=True)
    confirmation_source_enum.drop(op.get_bind(), checkfirst=True)
