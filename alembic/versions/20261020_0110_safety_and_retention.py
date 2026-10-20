"""Enforced content safety audit and purpose-ended learner erasure deadlines.

0109 is reserved for the separately held lesson-review redesign.
"""

import re

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20261020_0110"
down_revision = "20261019_0108"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("purpose_ended_at", "retention_due_at", "retention_purged_at"):
        op.add_column("users", sa.Column(name, sa.DateTime(timezone=True)))
    op.create_index("ix_users_retention_due_at", "users", ["retention_due_at"])
    op.alter_column("schools", "data_retention_days", server_default="180")
    op.execute("UPDATE schools SET data_retention_days = LEAST(data_retention_days, 180)")
    op.create_table(
        "content_safety_events",
        sa.Column("id", sa.Uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("school_id", sa.Uuid, sa.ForeignKey("schools.id", ondelete="CASCADE")),
        sa.Column("student_id", sa.Uuid, sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("actor_user_id", sa.Uuid, sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("phase", sa.String(100), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("categories", JSONB, nullable=False),
        sa.Column("policy_version", sa.String(60), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("acknowledged_by", sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    for field in ("school_id", "student_id"):
        op.create_index(f"ix_content_safety_events_{field}", "content_safety_events", [field])
    op.create_table(
        "learner_purge_receipts",
        sa.Column("id", sa.Uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "student_id", sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), unique=True
        ),
        sa.Column("school_id", sa.Uuid, sa.ForeignKey("schools.id", ondelete="SET NULL")),
        sa.Column("subject_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("object_paths", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("counts", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_code", sa.String(60)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_learner_purge_receipts_school_id", "learner_purge_receipts", ["school_id"])
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_signal_events_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE'
             AND current_setting('nevo.retention_student', true) = OLD.student_id::text
             AND EXISTS (SELECT 1 FROM users WHERE id = OLD.student_id
                         AND retention_due_at <= now() AND retention_purged_at IS NULL)
             AND EXISTS (SELECT 1 FROM learner_purge_receipts WHERE student_id = OLD.student_id
                         AND status IN ('pending', 'retry')) THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'signal_events rows are append-only';
        END $$;
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_learner_profile_history_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE'
             AND current_setting('nevo.retention_student', true) = OLD.learner_id::text
             AND EXISTS (SELECT 1 FROM users WHERE id = OLD.learner_id
                         AND retention_due_at <= now() AND retention_purged_at IS NULL)
             AND EXISTS (SELECT 1 FROM learner_purge_receipts WHERE student_id = OLD.learner_id
                         AND status IN ('pending', 'retry')) THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'learner profile history is immutable';
        END $$;
    """)
    statements = """
        CREATE FUNCTION nevo_retention_deadline() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE days integer;
        BEGIN
          IF NEW.role::text <> 'student' THEN RETURN NEW; END IF;
          IF NEW.status::text = 'deactivated' AND NEW.purpose_ended_at IS NULL THEN
            NEW.purpose_ended_at := COALESCE(NEW.deactivated_at, now());
          END IF;
          IF NEW.purpose_ended_at IS NOT NULL THEN
            SELECT LEAST(data_retention_days, 180) INTO days FROM schools WHERE id = NEW.school_id;
            NEW.retention_due_at := NEW.purpose_ended_at + make_interval(days => COALESCE(days, 180));
          ELSE
            NEW.retention_due_at := NULL;
          END IF;
          IF TG_OP = 'UPDATE' AND OLD.retention_purged_at IS NOT NULL THEN
            IF NEW.status::text <> 'deactivated' OR NEW.email IS NOT NULL OR NEW.school_id IS NOT NULL
               OR NEW.retention_purged_at IS NULL THEN
              RAISE EXCEPTION 'learner_retention_purged' USING ERRCODE = '23514';
            END IF;
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER users_retention_deadline BEFORE INSERT OR UPDATE ON users
          FOR EACH ROW EXECUTE FUNCTION nevo_retention_deadline();
        UPDATE users SET purpose_ended_at = deactivated_at
          WHERE role::text = 'student' AND deactivated_at IS NOT NULL;
        CREATE FUNCTION nevo_withdrawal_retention() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.consent_type::text = 'data_processing' AND NEW.status::text = 'withdrawn' THEN
            UPDATE users SET purpose_ended_at = COALESCE(purpose_ended_at, NEW.last_changed_at, now())
              WHERE id = NEW.subject_user_id AND role::text = 'student';
          ELSIF TG_OP = 'UPDATE' AND NEW.consent_type::text = 'data_processing'
              AND OLD.status::text = 'withdrawn' AND NEW.status::text = 'confirmed' THEN
            UPDATE users SET purpose_ended_at = NULL WHERE id = NEW.subject_user_id
              AND status::text = 'active' AND retention_purged_at IS NULL;
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER consent_withdrawal_retention AFTER INSERT OR UPDATE ON consent_records
          FOR EACH ROW EXECUTE FUNCTION nevo_withdrawal_retention();
        UPDATE users u SET purpose_ended_at = COALESCE(u.purpose_ended_at, c.last_changed_at, c.updated_at)
          FROM consent_records c WHERE c.subject_user_id = u.id AND u.role::text = 'student'
          AND c.consent_type::text = 'data_processing' AND c.status::text = 'withdrawn';
        CREATE FUNCTION nevo_refuse_purged_learner_write() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE subject uuid; purged timestamptz;
        BEGIN
          subject := (to_jsonb(NEW)->>TG_ARGV[0])::uuid;
          SELECT retention_purged_at INTO purged FROM users WHERE id = subject FOR KEY SHARE;
          IF purged IS NOT NULL THEN
            RAISE EXCEPTION 'learner_retention_purged' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END $$;
        CREATE FUNCTION nevo_refuse_purged_context_write() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE subject uuid; purged timestamptz;
        BEGIN
          subject := NULLIF(NEW.context_ids->>'studentId', '')::uuid;
          SELECT retention_purged_at INTO purged FROM users WHERE id = subject FOR KEY SHARE;
          IF purged IS NOT NULL THEN
            RAISE EXCEPTION 'learner_retention_purged' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER retention_guard_context BEFORE INSERT OR UPDATE ON ask_nevo_interactions
          FOR EACH ROW EXECUTE FUNCTION nevo_refuse_purged_context_write();
    """
    for statement in re.split(r"(?=\n        (?:CREATE|UPDATE) )", statements):
        if statement.strip():
            op.execute(statement.strip())
    # Lock the identity row for child-data writes, serialising with the purge.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    owned = {
        "student_id",
        "learner_id",
        "subject_user_id",
        "actor_user_id",
        "user_id",
        "sender_id",
        "recipient_id",
    }
    for table in inspector.get_table_names():
        if table in {"users", "learner_purge_receipts"}:
            continue
        for fk in inspector.get_foreign_keys(table):
            columns = fk["constrained_columns"]
            if fk["referred_table"] != "users" or len(columns) != 1:
                continue
            column = columns[0]
            if column not in owned and not (
                table == "ai_gateway_calls" and column == "requester_user_id"
            ):
                continue
            quote = bind.dialect.identifier_preparer.quote
            trigger = f"retention_guard_{column}"
            op.execute(
                sa.text(
                    f"CREATE TRIGGER {quote(trigger)} BEFORE INSERT OR UPDATE ON {quote(table)} FOR EACH ROW EXECUTE FUNCTION nevo_refuse_purged_learner_write('{column}')"
                )
            )


def downgrade():
    op.execute("DROP FUNCTION IF EXISTS nevo_refuse_purged_context_write() CASCADE")
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_learner_profile_history_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'learner profile history is immutable';
        END $$;
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_signal_events_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'signal_events rows are append-only';
        END $$;
    """)
    op.execute("DROP FUNCTION nevo_refuse_purged_learner_write() CASCADE")
    op.execute("DROP FUNCTION nevo_withdrawal_retention() CASCADE")
    op.execute("DROP FUNCTION nevo_retention_deadline() CASCADE")
    op.drop_table("content_safety_events")
    op.drop_table("learner_purge_receipts")
    op.drop_index("ix_users_retention_due_at", table_name="users")
    for name in ("retention_purged_at", "retention_due_at", "purpose_ended_at"):
        op.drop_column("users", name)
    op.alter_column("schools", "data_retention_days", server_default="365")
