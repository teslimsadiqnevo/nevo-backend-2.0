import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nevo.db.base import Base
from nevo.domain.accounts.vocabulary import (
    AuthMethod,
    ConsentMethod,
    ConsentStatus,
    ConsentType,
    SchoolEnrollmentBand,
    UserRole,
    UserStatus,
)

user_role_enum = Enum(
    UserRole,
    name="user_role",
    values_callable=lambda enum: [item.value for item in enum],
)
auth_method_enum = Enum(
    AuthMethod,
    name="auth_method",
    values_callable=lambda enum: [item.value for item in enum],
)
user_status_enum = Enum(
    UserStatus,
    name="user_status",
    values_callable=lambda enum: [item.value for item in enum],
)
enrollment_band_enum = Enum(
    SchoolEnrollmentBand,
    name="school_enrollment_band",
    values_callable=lambda enum: [item.value for item in enum],
)
consent_status_enum = Enum(
    ConsentStatus,
    name="consent_status",
    values_callable=lambda enum: [item.value for item in enum],
)
consent_type_enum = Enum(
    ConsentType,
    name="consent_type",
    values_callable=lambda enum: [item.value for item in enum],
)
consent_method_enum = Enum(
    ConsentMethod,
    name="consent_confirmed_via",
    values_callable=lambda enum: [item.value for item in enum],
)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class School(TimestampMixin, Base):
    __tablename__ = "schools"
    __table_args__ = (
        UniqueConstraint("school_code", name="uq_schools_school_code"),
        UniqueConstraint("school_url_slug", name="uq_schools_school_url_slug"),
        CheckConstraint(
            "data_retention_days > 0",
            name="data_retention_days_positive",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    school_code: Mapped[str] = mapped_column(String(50), nullable=False)
    school_url_slug: Mapped[str] = mapped_column(String(100), nullable=False)
    auth_method: Mapped[AuthMethod] = mapped_column(
        auth_method_enum,
        nullable=False,
        default=AuthMethod.EMAIL_PASSWORD,
        server_default=AuthMethod.EMAIL_PASSWORD.value,
    )
    enrollment_band: Mapped[SchoolEnrollmentBand | None] = mapped_column(
        enrollment_band_enum,
        nullable=True,
    )
    is_founding_partner: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    price_lock_expiry: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    data_retention_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=365,
        server_default="365",
    )

    users: Mapped[list["User"]] = relationship(back_populates="school")
    classes: Mapped[list["Class"]] = relationship(back_populates="school")


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        UniqueConstraint("sso_external_id", name="uq_users_sso_external_id"),
        CheckConstraint(
            "(status = 'deactivated') = (deactivated_at IS NOT NULL)",
            name="deactivated_at_matches_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    school_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("schools.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    role: Mapped[UserRole] = mapped_column(user_role_enum, nullable=False, index=True)
    auth_method: Mapped[AuthMethod] = mapped_column(auth_method_enum, nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pin_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sso_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_first_use: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    status: Mapped[UserStatus] = mapped_column(
        user_status_enum,
        nullable=False,
        default=UserStatus.ACTIVE,
        server_default=UserStatus.ACTIVE.value,
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    school: Mapped[School | None] = relationship(back_populates="users")


class Class(TimestampMixin, Base):
    __tablename__ = "classes"
    __table_args__ = (UniqueConstraint("class_code", name="uq_classes_class_code"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("schools.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    class_code: Mapped[str | None] = mapped_column(String(20), nullable=True)

    school: Mapped[School] = relationship(back_populates="classes")
    enrollments: Mapped[list["StudentClassEnrollment"]] = relationship(
        back_populates="school_class",
        passive_deletes=True,
    )


class StudentClassEnrollment(TimestampMixin, Base):
    __tablename__ = "student_class_enrollments"
    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "class_id",
            name="uq_student_class_enrollments_student_id_class_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("classes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    school_class: Mapped[Class] = relationship(back_populates="enrollments")


class ConsentRecord(TimestampMixin, Base):
    __tablename__ = "consent_records"
    __table_args__ = (
        UniqueConstraint(
            "subject_user_id",
            "consent_type",
            name="uq_consent_records_subject_user_id_consent_type",
        ),
        CheckConstraint(
            "(status = 'confirmed') = ("
            "confirmed_by_admin_id IS NOT NULL"
            " AND confirmed_via IS NOT NULL"
            " AND confirmed_at IS NOT NULL"
            ")",
            name="confirmation_fields_match_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    subject_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    consent_type: Mapped[ConsentType] = mapped_column(consent_type_enum, nullable=False)
    status: Mapped[ConsentStatus] = mapped_column(
        consent_status_enum,
        nullable=False,
        default=ConsentStatus.PENDING,
        server_default=ConsentStatus.PENDING.value,
    )
    confirmed_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    confirmed_via: Mapped[ConsentMethod | None] = mapped_column(
        consent_method_enum,
        nullable=True,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
