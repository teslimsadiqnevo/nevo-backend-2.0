"""Resolve admin consent, DPA, and invitation contract blockers.

Revision ID: 20260907_0041
Revises: 20260903_0040
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260907_0041"
down_revision: str | Sequence[str] | None = "20260903_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE consent_status ADD VALUE IF NOT EXISTS 'not_sent'")
        op.execute("ALTER TYPE consent_status ADD VALUE IF NOT EXISTS 'withdrawn'")
    op.drop_constraint(
        op.f("ck_consent_records_confirmation_fields_match_status"),
        "consent_records",
        type_="check",
    )
    op.add_column("consent_records", sa.Column("last_actor_user_id", sa.Uuid(), nullable=True))
    op.add_column(
        "consent_records", sa.Column("last_changed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("consent_records", sa.Column("last_channel", sa.String(40), nullable=True))
    op.create_foreign_key(
        "fk_consent_records_last_actor_user_id_users",
        "consent_records",
        "users",
        ["last_actor_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_consent_records_last_actor_user_id", "consent_records", ["last_actor_user_id"]
    )
    op.execute(
        """
        UPDATE consent_records
        SET last_actor_user_id = COALESCE(confirmed_by_admin_id, confirmed_by_parent_id),
            last_changed_at = confirmed_at,
            last_channel = confirmed_via::text
        WHERE status = 'confirmed'
        """
    )
    op.create_check_constraint(
        "confirmation_fields_match_status",
        "consent_records",
        """
        (status IN ('pending', 'not_sent')
         AND confirmation_source IS NULL
         AND confirmed_by_admin_id IS NULL
         AND confirmed_by_parent_id IS NULL
         AND confirmed_via IS NULL
         AND confirmed_at IS NULL)
        OR
        (status IN ('confirmed', 'withdrawn')
         AND confirmed_via IS NOT NULL
         AND confirmed_at IS NOT NULL
         AND ((confirmation_source = 'school' AND confirmed_by_admin_id IS NOT NULL
               AND confirmed_by_parent_id IS NULL)
              OR (confirmation_source = 'parent' AND confirmed_by_parent_id IS NOT NULL
                  AND confirmed_by_admin_id IS NULL)))
        """,
    )

    op.add_column(
        "school_invitations",
        sa.Column(
            "consent_request_status", sa.String(24), server_default="not_sent", nullable=False
        ),
    )

    op.create_table(
        "dpa_acceptances",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("accepted_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "accepted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["accepted_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("school_id", "version", name="uq_dpa_acceptances_school_version"),
    )
    op.create_index(
        "ix_dpa_acceptances_school_accepted", "dpa_acceptances", ["school_id", "accepted_at"]
    )

    op.execute("UPDATE ai_prompt_templates SET active = false WHERE name = 'content_parse.default'")
    op.execute(
        """
        INSERT INTO ai_prompt_templates (
            service, name, version, system_template, user_template,
            required_variables, active
        )
        VALUES (
            'lesson_generation',
            'content_parse.default',
            3,
            'You parse teacher lesson sources into curriculum-agnostic structured segments. Return strict JSON only. Use warm functional learning language. Avoid prohibited learner labels.',
            'Parse lesson {lesson_title} from {source_type}. This is chunk {chunk_number} of {chunk_count}. Return a JSON object with a segments array containing at least three useful segments. Each segment must include content_type, sequence_order, title, body, availableModalities, comprehension_checkpoints, optional text_variant, visual_variant, audio_variant, interactive_variant, calculation_variant, needs_review, and review_reasons. Across the lesson include at least one comprehension checkpoint with conceptName, prompt, answerType, at least two value-label options, answerKey, explanation, and position. Every answerKey must be supported by the supplied source. Include at least one useful visual variant and one audio variant with a narration script. Allowed content_type values are explanatory_text, visual_diagram, worked_example, practice_question, definition, summary, calculation. For every non-calculation segment, text is always available and another useful modality should be present when possible. Use only visual, audio, text, interactive. If fewer than two modalities are appropriate, flag the segment for teacher review. For calculation segments, decompose into co_construction steps and set availableModalities to interactive and visual only. Include narrationAudio placeholders in calculation steps when a script can be written. Source follows. {source_text}',
            '["lesson_title","source_type","chunk_number","chunk_count","source_text"]'::jsonb,
            true
        )
        ON CONFLICT (name, version) DO UPDATE SET active = true
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM ai_prompt_templates WHERE name = 'content_parse.default' AND version = 3"
    )
    op.execute(
        "UPDATE ai_prompt_templates SET active = true "
        "WHERE name = 'content_parse.default' AND version = 2"
    )
    op.drop_index("ix_dpa_acceptances_school_accepted", table_name="dpa_acceptances")
    op.drop_table("dpa_acceptances")
    op.drop_column("school_invitations", "consent_request_status")
    op.drop_constraint(
        op.f("ck_consent_records_confirmation_fields_match_status"),
        "consent_records",
        type_="check",
    )
    op.drop_index("ix_consent_records_last_actor_user_id", table_name="consent_records")
    op.drop_constraint(
        "fk_consent_records_last_actor_user_id_users", "consent_records", type_="foreignkey"
    )
    op.drop_column("consent_records", "last_channel")
    op.drop_column("consent_records", "last_changed_at")
    op.drop_column("consent_records", "last_actor_user_id")
    op.execute("UPDATE consent_records SET status = 'pending' WHERE status = 'not_sent'")
    op.execute("UPDATE consent_records SET status = 'confirmed' WHERE status = 'withdrawn'")
    op.create_check_constraint(
        "confirmation_fields_match_status",
        "consent_records",
        """
        (status = 'pending' AND confirmation_source IS NULL
         AND confirmed_by_admin_id IS NULL AND confirmed_by_parent_id IS NULL
         AND confirmed_via IS NULL AND confirmed_at IS NULL)
        OR
        (status = 'confirmed' AND confirmed_via IS NOT NULL AND confirmed_at IS NOT NULL
         AND ((confirmation_source = 'school' AND confirmed_by_admin_id IS NOT NULL
               AND confirmed_by_parent_id IS NULL)
              OR (confirmation_source = 'parent' AND confirmed_by_parent_id IS NOT NULL
                  AND confirmed_by_admin_id IS NULL)))
        """,
    )
