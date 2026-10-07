import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nevo.db.base import Base
from nevo.domain.accounts.classes import (
    WHITESPACE,
    academic_session,
    normalise_class_name,
)
from nevo.domain.accounts.vocabulary import (
    AuthMethod,
    ConsentMethod,
    ConsentStatus,
    ConsentType,
    SchoolEnrollmentBand,
    UserRole,
    UserStatus,
)
from nevo.domain.billing.vocabulary import PaymentSource, PricingPlan, SubscriptionTier
from nevo.domain.consent.vocabulary import ConsentConfirmationSource

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
pricing_plan_enum = Enum(
    PricingPlan,
    name="pricing_plan",
    values_callable=lambda enum: [item.value for item in enum],
)
subscription_tier_enum = Enum(
    SubscriptionTier,
    name="subscription_tier",
    values_callable=lambda enum: [item.value for item in enum],
)
payment_source_enum = Enum(
    PaymentSource,
    name="payment_source",
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
consent_confirmation_source_enum = Enum(
    ConsentConfirmationSource,
    name="consent_confirmation_source",
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
        CheckConstraint(
            "contract_value IS NULL OR contract_value >= 0",
            name="contract_value_nonnegative",
        ),
        CheckConstraint(
            "contract_start IS NULL OR contract_end IS NULL OR contract_end >= contract_start",
            name="contract_dates_ordered",
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
    profile: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    academic_config: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    retention_policy: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="contract",
        server_default="contract",
    )
    subscription_tier: Mapped[SubscriptionTier | None] = mapped_column(
        subscription_tier_enum,
        nullable=True,
    )
    payment_source: Mapped[PaymentSource] = mapped_column(
        payment_source_enum,
        nullable=False,
        default=PaymentSource.DIRECT,
        server_default=PaymentSource.DIRECT.value,
    )
    contract_value: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )
    pricing_plan: Mapped[PricingPlan] = mapped_column(
        pricing_plan_enum,
        nullable=False,
        default=PricingPlan.ANNUAL,
        server_default=PricingPlan.ANNUAL.value,
    )
    per_student_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )
    contract_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    contract_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    billing_contact_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("billing_contacts.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )

    users: Mapped[list["User"]] = relationship(back_populates="school")
    classes: Mapped[list["Class"]] = relationship(back_populates="school")


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        UniqueConstraint("sso_external_id", name="uq_users_sso_external_id"),
        UniqueConstraint(
            "school_id",
            "login_identifier",
            name="uq_users_school_id_login_identifier",
        ),
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
    #: When this person proved they own the address. Null on an administrator
    #: means they may read the console and write nothing to it, which is
    #: enforced in actor_user rather than by each handler remembering.
    email_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    login_identifier: Mapped[str | None] = mapped_column(String(50), nullable=True)
    #: The school's own Student ID or Admission Number, and the child's
    #: identity at sign-in. SCRUM-202.
    #:
    #: Any string. Nigerian schools format these completely differently -
    #: TEST/2024/001, 2024017 and NBA/JSS2/17 are all normal - so the shape is
    #: not validated, only uniqueness within the school. Validating the shape
    #: would reject valid rosters.
    #:
    #: Deliberately not called student_id: that name is the internal primary
    #: key, including on parent_links, and two different things under one name
    #: is a real bug waiting to happen.
    admission_number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pin_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Set only when a class teacher deliberately opens the replacement-PIN
    #: window. A null PIN alone also describes a child who has never onboarded,
    #: so it cannot authorize the clear-only recovery route by itself.
    pin_cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sso_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    baseline_profile: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    engine_config: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    preferences: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    #: A stable presentation preference, separate from the open-ended settings
    #: bag so profile identity does not depend on an untyped key forever.
    avatar_tone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    age_band: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: What the child asked to be called, from "What should we call you?".
    #:
    #: Its own column rather than overwriting first_name, because the roster
    #: name is the school's record of a child and a nickname is not a
    #: correction to it. Had nowhere typed to live before this, so the screen
    #: that asks the question had nowhere to put the answer. Ask B35.
    preferred_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    #: From the school's roster. Age is derived from it wherever a screen
    #: needs one, so a child is never asked for what the school already told
    #: us - and the two-point age check has something to check against.
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
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
    anonymised_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    school: Mapped[School | None] = relationship(back_populates="users")


Index(
    "uq_schools_school_code_ci",
    func.lower(School.school_code),
    unique=True,
)
Index(
    "uq_users_email_ci",
    func.lower(User.email),
    unique=True,
    postgresql_where=User.email.is_not(None),
)
Index(
    "uq_users_school_login_identifier_ci",
    User.school_id,
    func.lower(User.login_identifier),
    unique=True,
    postgresql_where=User.login_identifier.is_not(None),
)
# Unique on the pair, not globally. Brightgate's 2024/001 and Corona's
# 2024/001 are two different children and neither blocks the other. Case
# insensitive, because a school will write adm001 in one file and ADM001 in
# the next and mean the same child. SCRUM-202.
Index(
    "uq_users_school_admission_number_ci",
    User.school_id,
    func.lower(User.admission_number),
    unique=True,
    postgresql_where=User.admission_number.is_not(None),
)


class Class(TimestampMixin, Base):
    __tablename__ = "classes"
    __table_args__ = (
        UniqueConstraint("class_code", name="uq_classes_class_code"),
        # One JSS 1A per school per school year. Two of them is one class's
        # children split between two rosters with nobody told.
        Index(
            "uq_classes_school_session_name",
            "school_id",
            "academic_session",
            "normalised_name",
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
        CheckConstraint("capacity IS NULL OR capacity > 0", name="class_capacity_positive"),
    )

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
    #: The name with case and spacing taken out of the comparison. Written by
    #: the listener below, never by a caller, because a caller that forgets is
    #: how a school gets two JSS 1As.
    normalised_name: Mapped[str] = mapped_column(String(255), nullable=False)
    class_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    year_group: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: "A" of "JSS 2A". Optional, because a school may name a class anything.
    section: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: Which school year this class is. Not optional even though capacity is:
    #: without it, next year's JSS 1A is this year's.
    academic_session: Mapped[str] = mapped_column(String(20), nullable=False)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="manual", server_default="manual"
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
            "("
            "status IN ('pending', 'not_sent')"
            " AND confirmation_source IS NULL"
            " AND confirmed_by_admin_id IS NULL"
            " AND confirmed_by_parent_id IS NULL"
            " AND confirmed_via IS NULL"
            " AND confirmed_at IS NULL"
            ") OR ("
            "status IN ('confirmed', 'withdrawn')"
            " AND confirmed_via IS NOT NULL"
            " AND confirmed_at IS NOT NULL"
            " AND ("
            "("
            "confirmation_source = 'school'"
            " AND confirmed_by_admin_id IS NOT NULL"
            " AND confirmed_by_parent_id IS NULL"
            ") OR ("
            "confirmation_source = 'parent'"
            " AND confirmed_by_parent_id IS NOT NULL"
            " AND confirmed_by_admin_id IS NULL"
            ")"
            ")"
            ")",
            name="confirmation_fields_match_status",
        ),
        CheckConstraint(
            "confirmed_via <> 'written'"
            " OR (parent_name_on_form IS NOT NULL"
            " AND signed_on IS NOT NULL"
            " AND notice_version IS NOT NULL)",
            name="written_consent_identifies_the_parent",
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
    confirmed_by_parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    confirmation_source: Mapped[ConsentConfirmationSource | None] = mapped_column(
        consent_confirmation_source_enum,
        nullable=True,
    )
    confirmed_via: Mapped[ConsentMethod | None] = mapped_column(
        consent_method_enum,
        nullable=True,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    last_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_channel: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: Who actually consented, as written on the paper form. Where a school
    #: confirms on a parent's behalf the record used to name the school
    #: administrator, which means it did not identify the person who
    #: consented at all.
    parent_name_on_form: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Mother, father, guardian. Part of the definition of a consent record
    #: and absent from every row until now.
    parent_relationship: Mapped[str | None] = mapped_column(String(80), nullable=True)
    #: The date the parent wrote on the form, which is not the date the school
    #: got round to uploading it.
    signed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: The version of the privacy notice the parent was shown. "They
    #: consented" says nothing without what they were reading when they did.
    notice_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: The photograph or scan of the signed form, in Nevo's storage.
    evidence_storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


@event.listens_for(Class, "before_insert")
@event.listens_for(Class, "before_update")
def _class_name_is_normalised(mapper: object, connection: object, target: Class) -> None:
    """Keep the compared form of the name in step with the name itself.

    Set here rather than at each call site because there are now several -
    a manual create, the year-group grid, and classes derived from a school's
    uploaded files - and a caller that forgets is how a school ends up with
    two JSS 1As and a roster holding half a class.
    """

    target.name = WHITESPACE.sub(" ", target.name).strip()
    target.normalised_name = normalise_class_name(target.name)
    if not target.academic_session:
        target.academic_session = academic_session(datetime.now(UTC).date())
