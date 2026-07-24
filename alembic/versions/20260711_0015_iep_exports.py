"""Add IEP export workflow."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260711_0015"
down_revision: str | None = "20260710_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


iep_export_status = postgresql.ENUM(
    "draft",
    "final",
    name="iep_export_status",
)
iep_export_share_status = postgresql.ENUM(
    "shared",
    "revoked",
    name="iep_export_share_status",
)
student_record_event_type = postgresql.ENUM(
    "export_draft_created",
    "export_draft_edited",
    "export_finalized",
    "export_shared",
    name="student_record_event_type",
)


def upgrade() -> None:
    bind = op.get_bind()
    iep_export_status.create(bind, checkfirst=True)
    iep_export_share_status.create(bind, checkfirst=True)
    student_record_event_type.create(bind, checkfirst=True)

    op.create_table(
        "iep_exports",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column(
            "status",
            iep_export_status,
            server_default="draft",
            nullable=False,
        ),
        sa.Column("export_content", sa.Text(), nullable=False),
        sa.Column(
            "source_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "annotations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("ai_gateway_call_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "period_end >= period_start",
            name=op.f("ck_iep_exports_period_order_valid"),
        ),
        sa.CheckConstraint(
            "(status = 'final') = (reviewed_by_user_id IS NOT NULL AND reviewed_at IS NOT NULL)",
            name=op.f("ck_iep_exports_final_requires_senco_review"),
        ),
        sa.ForeignKeyConstraint(
            ["ai_gateway_call_id"],
            ["ai_gateway_calls.id"],
            name=op.f("fk_iep_exports_ai_gateway_call_id_ai_gateway_calls"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name=op.f("fk_iep_exports_requested_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            name=op.f("fk_iep_exports_reviewed_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["users.id"],
            name=op.f("fk_iep_exports_student_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_iep_exports")),
    )
    op.create_index(
        "ix_iep_exports_status_created",
        "iep_exports",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_iep_exports_student_period",
        "iep_exports",
        ["student_id", "period_start", "period_end"],
    )

    op.create_table(
        "iep_export_shares",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("export_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=False),
        sa.Column("shared_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            iep_export_share_status,
            server_default="shared",
            nullable=False,
        ),
        sa.Column(
            "shared_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["export_id"],
            ["iep_exports.id"],
            name=op.f("fk_iep_export_shares_export_id_iep_exports"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["users.id"],
            name=op.f("fk_iep_export_shares_parent_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["shared_by_user_id"],
            ["users.id"],
            name=op.f("fk_iep_export_shares_shared_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["users.id"],
            name=op.f("fk_iep_export_shares_student_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_iep_export_shares")),
        sa.UniqueConstraint(
            "export_id",
            "parent_id",
            name="uq_iep_export_shares_export_parent",
        ),
    )
    op.create_index(
        "ix_iep_export_shares_parent_shared",
        "iep_export_shares",
        ["parent_id", "shared_at"],
    )

    op.create_table(
        "student_record_events",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("export_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", student_record_event_type, nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_student_record_events_actor_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["export_id"],
            ["iep_exports.id"],
            name=op.f("fk_student_record_events_export_id_iep_exports"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["users.id"],
            name=op.f("fk_student_record_events_student_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_student_record_events")),
    )
    op.create_index(
        "ix_student_record_events_export_created",
        "student_record_events",
        ["export_id", "created_at"],
    )
    op.create_index(
        "ix_student_record_events_student_created",
        "student_record_events",
        ["student_id", "created_at"],
    )

    op.execute(
        """
        INSERT INTO ai_prompt_templates (
            service,
            name,
            version,
            system_template,
            user_template,
            required_variables,
            active
        )
        VALUES (
            'narrative',
            'iep_export.draft',
            1,
            'You write board-ready learner progress documents for schools. Use functional language only, based on observed learning patterns and support actions. Avoid labels and sensitive inferred categories. Return polished markdown.',
            'Create a draft progress document for {student_name} covering {period_start} to {period_end}. Use this evidence summary and keep the writing concise, practical, and suitable for SENCo review before final sharing. Evidence summary follows. {evidence_summary}',
            '["student_name","period_start","period_end","evidence_summary"]'::jsonb,
            true
        )
        ON CONFLICT (name, version) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM ai_prompt_templates
        WHERE name = 'iep_export.draft'
          AND version = 1
        """
    )
    op.drop_index(
        "ix_student_record_events_student_created",
        table_name="student_record_events",
    )
    op.drop_index(
        "ix_student_record_events_export_created",
        table_name="student_record_events",
    )
    op.drop_table("student_record_events")
    op.drop_index(
        "ix_iep_export_shares_parent_shared",
        table_name="iep_export_shares",
    )
    op.drop_table("iep_export_shares")
    op.drop_index("ix_iep_exports_student_period", table_name="iep_exports")
    op.drop_index("ix_iep_exports_status_created", table_name="iep_exports")
    op.drop_table("iep_exports")
    student_record_event_type.drop(op.get_bind(), checkfirst=True)
    iep_export_share_status.drop(op.get_bind(), checkfirst=True)
    iep_export_status.drop(op.get_bind(), checkfirst=True)
