"""Create core account tables: schools, users, classes, enrollments, consent.

Revision ID: 20260702_0002
Revises: 20260702_0001
Create Date: 2026-07-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260702_0002"
down_revision: str | Sequence[str] | None = "20260702_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_role_values = ("student", "teacher", "senco_admin", "other_admin")
auth_method_values = ("email_password", "pin", "sso")
user_status_values = ("active", "invited", "deactivated")
enrollment_band_values = ("small", "medium", "large", "very_large")
consent_status_values = ("pending", "confirmed")
consent_type_values = ("data_processing", "camera", "offline_storage")
consent_method_values = ("written", "verbal", "email", "digital")

user_role_enum = postgresql.ENUM(*user_role_values, name="user_role", create_type=False)
auth_method_enum = postgresql.ENUM(
    *auth_method_values, name="auth_method", create_type=False
)
user_status_enum = postgresql.ENUM(
    *user_status_values, name="user_status", create_type=False
)
enrollment_band_enum = postgresql.ENUM(
    *enrollment_band_values, name="school_enrollment_band", create_type=False
)
consent_status_enum = postgresql.ENUM(
    *consent_status_values, name="consent_status", create_type=False
)
consent_type_enum = postgresql.ENUM(
    *consent_type_values, name="consent_type", create_type=False
)
consent_method_enum = postgresql.ENUM(
    *consent_method_values, name="consent_confirmed_via", create_type=False
)

_all_enums = (
    user_role_enum,
    auth_method_enum,
    user_status_enum,
    enrollment_band_enum,
    consent_status_enum,
    consent_type_enum,
    consent_method_enum,
)


def upgrade() -> None:
    bind = op.get_bind()
    for enum in _all_enums:
        enum.create(bind, checkfirst=True)

    op.create_table(
        "schools",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("school_code", sa.String(length=50), nullable=False),
        sa.Column("school_url_slug", sa.String(length=100), nullable=False),
        sa.Column(
            "auth_method",
            auth_method_enum,
            nullable=False,
            server_default="email_password",
        ),
        sa.Column("enrollment_band", enrollment_band_enum, nullable=True),
        sa.Column(
            "is_founding_partner",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("price_lock_expiry", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "data_retention_days",
            sa.Integer(),
            nullable=False,
            server_default="365",
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
        sa.CheckConstraint(
            "data_retention_days > 0",
            name="data_retention_days_positive",
        ),
        sa.UniqueConstraint("school_code", name="uq_schools_school_code"),
        sa.UniqueConstraint("school_url_slug", name="uq_schools_school_url_slug"),
    )

    op.create_table(
        "users",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "school_id",
            sa.Uuid(),
            sa.ForeignKey(
                "schools.id",
                name="fk_users_school_id_schools",
                ondelete="RESTRICT",
            ),
            nullable=True,
        ),
        sa.Column("role", user_role_enum, nullable=False),
        sa.Column("auth_method", auth_method_enum, nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=True),
        sa.Column("last_name", sa.String(length=100), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("pin_hash", sa.String(length=255), nullable=True),
        sa.Column("sso_external_id", sa.String(length=255), nullable=True),
        sa.Column(
            "is_first_use",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "status",
            user_status_enum,
            nullable=False,
            server_default="active",
        ),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "(status = 'deactivated') = (deactivated_at IS NOT NULL)",
            name="deactivated_at_matches_status",
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("sso_external_id", name="uq_users_sso_external_id"),
    )
    op.create_index("ix_users_school_id", "users", ["school_id"])
    op.create_index("ix_users_role", "users", ["role"])

    op.create_table(
        "classes",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "school_id",
            sa.Uuid(),
            sa.ForeignKey(
                "schools.id",
                name="fk_classes_school_id_schools",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("class_code", sa.String(length=20), nullable=True),
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
        sa.UniqueConstraint("class_code", name="uq_classes_class_code"),
    )
    op.create_index("ix_classes_school_id", "classes", ["school_id"])

    op.create_table(
        "student_class_enrollments",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "student_id",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id",
                name="fk_student_class_enrollments_student_id_users",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column(
            "class_id",
            sa.Uuid(),
            sa.ForeignKey(
                "classes.id",
                name="fk_student_class_enrollments_class_id_classes",
                ondelete="CASCADE",
            ),
            nullable=False,
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
            "class_id",
            name="uq_student_class_enrollments_student_id_class_id",
        ),
    )
    op.create_index(
        "ix_student_class_enrollments_student_id",
        "student_class_enrollments",
        ["student_id"],
    )
    op.create_index(
        "ix_student_class_enrollments_class_id",
        "student_class_enrollments",
        ["class_id"],
    )

    op.create_table(
        "consent_records",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "subject_user_id",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id",
                name="fk_consent_records_subject_user_id_users",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("consent_type", consent_type_enum, nullable=False),
        sa.Column(
            "status",
            consent_status_enum,
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "confirmed_by_admin_id",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id",
                name="fk_consent_records_confirmed_by_admin_id_users",
                ondelete="RESTRICT",
            ),
            nullable=True,
        ),
        sa.Column("confirmed_via", consent_method_enum, nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "(status = 'confirmed') = ("
            "confirmed_by_admin_id IS NOT NULL"
            " AND confirmed_via IS NOT NULL"
            " AND confirmed_at IS NOT NULL"
            ")",
            name="confirmation_fields_match_status",
        ),
        sa.UniqueConstraint(
            "subject_user_id",
            "consent_type",
            name="uq_consent_records_subject_user_id_consent_type",
        ),
    )
    op.create_index(
        "ix_consent_records_subject_user_id",
        "consent_records",
        ["subject_user_id"],
    )
    op.create_index(
        "ix_consent_records_confirmed_by_admin_id",
        "consent_records",
        ["confirmed_by_admin_id"],
    )

    # Close the SCRUM-15 deferred dependency: learner_id now references the
    # canonical users table (see docs/adr/0001 and docs/adr/0002).
    op.create_foreign_key(
        "fk_learner_profiles_learner_id_users",
        "learner_profiles",
        "users",
        ["learner_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_learner_profile_history_learner_id_users",
        "learner_profile_history",
        "users",
        ["learner_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_learner_profile_history_learner_id_users",
        "learner_profile_history",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_learner_profiles_learner_id_users",
        "learner_profiles",
        type_="foreignkey",
    )

    op.drop_table("consent_records")
    op.drop_table("student_class_enrollments")
    op.drop_table("classes")
    op.drop_table("users")
    op.drop_table("schools")

    bind = op.get_bind()
    for enum in reversed(_all_enums):
        enum.drop(bind, checkfirst=True)
