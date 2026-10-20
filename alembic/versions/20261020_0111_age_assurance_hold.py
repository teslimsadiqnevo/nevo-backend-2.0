"""DOB holds and a non-resettable 30-day notification-anchored purge deadline."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20261020_0111"
down_revision = "20261020_0110"
branch_labels = depends_on = None


def upgrade():
    for name in ("school_notified_at", "school_rechecked_at", "parent_reconfirmed_at"):
        op.add_column("age_checks", sa.Column(name, sa.DateTime(timezone=True)))
    for name in ("school_rechecked_by", "parent_reconfirmed_by"):
        op.add_column(
            "age_checks", sa.Column(name, sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"))
        )
    op.add_column("age_checks", sa.Column("enrolled_age_band", sa.String(40)))
    op.add_column("age_checks", sa.Column("band_checked_on", sa.Date()))
    op.add_column(
        "age_checks",
        sa.Column("hold_reasons", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.create_index(
        "ix_age_checks_notification_deadline",
        "age_checks",
        ["school_notified_at"],
        postgresql_where=sa.text("state = 'mismatch'"),
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION nevo_retention_deadline() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE days integer; age_deadline timestamptz; pending_school date; pending_parent date;
        BEGIN
          IF NEW.role::text <> 'student' THEN RETURN NEW; END IF;
          IF NEW.status::text = 'deactivated' AND NEW.purpose_ended_at IS NULL THEN
            NEW.purpose_ended_at := COALESCE(NEW.deactivated_at, now());
          END IF;
          IF NEW.purpose_ended_at IS NOT NULL THEN
            SELECT LEAST(data_retention_days, 180) INTO days FROM schools WHERE id = NEW.school_id;
            NEW.retention_due_at := NEW.purpose_ended_at + make_interval(days => COALESCE(days, 180));
          ELSE NEW.retention_due_at := NULL;
          END IF;
          SELECT school_notified_at + interval '30 days', school_date_of_birth, parent_date_of_birth
            INTO age_deadline, pending_school, pending_parent FROM age_checks
            WHERE student_id = NEW.id AND state = 'mismatch';
          IF FOUND THEN
            NEW.retention_due_at := LEAST(NEW.retention_due_at, age_deadline);
            NEW.date_of_birth := GREATEST(pending_school, pending_parent);
            NEW.age_band := CASE
              WHEN NEW.date_of_birth IS NULL THEN NULL
              WHEN date_part('year', age(current_date, NEW.date_of_birth)) <= 8 THEN 'early_primary'
              WHEN date_part('year', age(current_date, NEW.date_of_birth)) <= 11 THEN 'upper_primary'
              WHEN date_part('year', age(current_date, NEW.date_of_birth)) <= 14 THEN 'junior_secondary'
              ELSE 'senior_secondary' END;
          END IF;
          IF TG_OP = 'UPDATE' AND OLD.retention_purged_at IS NOT NULL THEN
            IF NEW.status::text <> 'deactivated' OR NEW.email IS NOT NULL OR NEW.school_id IS NOT NULL
               OR NEW.retention_purged_at IS NULL THEN
              RAISE EXCEPTION 'learner_retention_purged' USING ERRCODE = '23514';
            END IF;
          END IF;
          RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE FUNCTION nevo_age_check_deadline() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          UPDATE users SET updated_at = now() WHERE id = NEW.student_id;
          RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE TRIGGER age_check_deadline AFTER INSERT OR UPDATE ON age_checks
        FOR EACH ROW EXECUTE FUNCTION nevo_age_check_deadline();
    """)
    # Freeze the existing year-group vocabulary in this migration, rather than
    # depending on whatever the application mapping becomes in a future release.
    op.execute("""
        CREATE FUNCTION pg_temp.nevo_enrolment_band(value text) RETURNS text
        LANGUAGE plpgsql IMMUTABLE AS $$
        DECLARE v text; y integer;
        BEGIN
          v := regexp_replace(lower(COALESCE(value, '')), '[^a-z0-9]', '', 'g');
          IF v ~ '^(nursery|reception)' THEN RETURN 'early_primary'; END IF;
          IF v ~ '^(primary|pry|p)' AND v ~ '[0-9]+' THEN
            y := substring(v FROM '[0-9]+')::integer;
            RETURN CASE WHEN y <= 3 THEN 'early_primary' ELSE 'upper_primary' END;
          END IF;
          IF v ~ '^(jss|js|juniorsecondary)' THEN RETURN 'junior_secondary'; END IF;
          IF v ~ '^(sss|ss|seniorsecondary)' THEN RETURN 'senior_secondary'; END IF;
          RETURN NULL;
        END $$;
    """)
    op.execute("""
        CREATE FUNCTION pg_temp.nevo_birth_band(born date) RETURNS text
        LANGUAGE sql STABLE AS $$
          SELECT CASE
            WHEN born IS NULL OR born > current_date THEN NULL
            WHEN date_part('year', age(current_date, born)) <= 8 THEN 'early_primary'
            WHEN date_part('year', age(current_date, born)) <= 11 THEN 'upper_primary'
            WHEN date_part('year', age(current_date, born)) <= 14 THEN 'junior_secondary'
            ELSE 'senior_secondary' END;
        $$;
    """)
    op.execute("""
        WITH bands AS (
          SELECT a.id,
            CASE WHEN count(DISTINCT pg_temp.nevo_enrolment_band(c.year_group)) = 1
                 AND count(*) FILTER (WHERE pg_temp.nevo_enrolment_band(c.year_group) IS NULL) = 0
            THEN min(pg_temp.nevo_enrolment_band(c.year_group)) ELSE NULL END AS band
          FROM age_checks a LEFT JOIN student_class_enrollments e ON e.student_id = a.student_id
          LEFT JOIN classes c ON c.id = e.class_id AND c.school_id = a.school_id
          GROUP BY a.id
        ) UPDATE age_checks a SET enrolled_age_band = b.band, band_checked_on = current_date
          FROM bands b WHERE b.id = a.id;
    """)
    # Old non-blocking resolutions cannot substitute for fresh confirmation.
    op.execute("""
        UPDATE age_checks SET state = 'mismatch', agreed_date_of_birth = NULL,
          resolved_at = NULL, resolved_by_user_id = NULL,
          hold_reasons = '["reconfirmation_required"]'::jsonb
        WHERE state = 'mismatch' OR (
          parent_date_of_birth IS NOT NULL AND (
            school_date_of_birth IS DISTINCT FROM parent_date_of_birth
            OR enrolled_age_band IS NULL
            OR pg_temp.nevo_birth_band(school_date_of_birth) IS DISTINCT FROM enrolled_age_band
            OR pg_temp.nevo_birth_band(parent_date_of_birth) IS DISTINCT FROM enrolled_age_band
          )
        );
    """)


def downgrade():
    raise RuntimeError(
        "DOB hold policy cannot be silently rolled back; use a reviewed forward migration"
    )
