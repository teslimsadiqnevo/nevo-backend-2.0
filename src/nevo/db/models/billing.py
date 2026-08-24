import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base
from nevo.domain.billing.vocabulary import (
    ContractStatus,
    InvoiceStatus,
    PaymentMethodType,
    PaymentSource,
    PricingCurrency,
    SubscriptionTier,
)

subscription_tier_enum = Enum(
    SubscriptionTier,
    name="subscription_tier",
    values_callable=lambda enum: [item.value for item in enum],
)
invoice_status_enum = Enum(
    InvoiceStatus,
    name="invoice_status",
    values_callable=lambda enum: [item.value for item in enum],
)
payment_method_type_enum = Enum(
    PaymentMethodType,
    name="payment_method_type",
    values_callable=lambda enum: [item.value for item in enum],
)
pricing_currency_enum = Enum(
    PricingCurrency,
    name="pricing_currency",
    values_callable=lambda enum: [item.value for item in enum],
)
contract_status_enum = Enum(
    ContractStatus,
    name="contract_status",
    values_callable=lambda enum: [item.value for item in enum],
)
payment_source_enum = Enum(
    PaymentSource,
    name="payment_source",
    values_callable=lambda enum: [item.value for item in enum],
)


class BillingSubscriptionTier(Base):
    __tablename__ = "subscription_tiers"
    __table_args__ = (
        UniqueConstraint("tier_name", name="uq_subscription_tiers_tier_name"),
        CheckConstraint("min_pupils >= 0", name="subscription_tier_min_pupils_valid"),
        CheckConstraint("max_pupils >= min_pupils", name="subscription_tier_boundary"),
        CheckConstraint(
            "founding_partner_usd_rate >= 0 AND commercial_usd_rate >= 0",
            name="subscription_tier_rates_nonnegative",
        ),
        CheckConstraint("vat_rate >= 0", name="subscription_tier_vat_nonnegative"),
    )

    tier_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tier_name: Mapped[SubscriptionTier] = mapped_column(
        subscription_tier_enum,
        nullable=False,
    )
    min_pupils: Mapped[int] = mapped_column(nullable=False)
    max_pupils: Mapped[int] = mapped_column(nullable=False)
    founding_partner_usd_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )
    commercial_usd_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )
    vat_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=Decimal("7.50"),
        server_default="7.50",
    )


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"
    __table_args__ = (
        CheckConstraint("conversion_rate > 0", name="exchange_rate_positive"),
        CheckConstraint(
            "volatility_buffer_percent >= 0",
            name="exchange_rate_buffer_nonnegative",
        ),
        CheckConstraint(
            "effective_end >= effective_start",
            name="exchange_rate_dates_ordered",
        ),
        Index(
            "ix_exchange_rates_pair_effective",
            "source_currency",
            "target_currency",
            "effective_start",
            "effective_end",
        ),
    )

    rate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    source_currency: Mapped[PricingCurrency] = mapped_column(
        pricing_currency_enum,
        nullable=False,
    )
    target_currency: Mapped[PricingCurrency] = mapped_column(
        pricing_currency_enum,
        nullable=False,
    )
    conversion_rate: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    volatility_buffer_percent: Mapped[Decimal] = mapped_column(
        Numeric(4, 2),
        nullable=False,
        default=Decimal("5.00"),
        server_default="5.00",
    )
    effective_start: Mapped[date] = mapped_column(Date, nullable=False)
    effective_end: Mapped[date] = mapped_column(Date, nullable=False)


class Contract(Base):
    __tablename__ = "contracts"
    __table_args__ = (
        CheckConstraint(
            "current_year_index BETWEEN 1 AND 6",
            name="contract_year_index_valid",
        ),
        CheckConstraint("end_date >= start_date", name="contract_dates_valid"),
        Index("ix_contracts_school_status", "school_id", "status"),
    )

    contract_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
    )
    tier_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("subscription_tiers.tier_id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[ContractStatus] = mapped_column(
        contract_status_enum,
        nullable=False,
        default=ContractStatus.ACTIVE,
        server_default=ContractStatus.ACTIVE.value,
    )
    is_founding_partner: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    payment_source: Mapped[PaymentSource] = mapped_column(
        payment_source_enum,
        nullable=False,
        default=PaymentSource.DIRECT,
        server_default=PaymentSource.DIRECT.value,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    current_year_index: Mapped[int] = mapped_column(
        nullable=False,
        default=1,
        server_default="1",
    )


class StepUpSchedule(Base):
    __tablename__ = "step_up_schedules"
    __table_args__ = (
        UniqueConstraint(
            "contract_id",
            "year_index",
            name="uq_step_up_schedules_contract_year",
        ),
        CheckConstraint("year_index BETWEEN 1 AND 6", name="step_up_year_valid"),
        CheckConstraint(
            "discount_percentage BETWEEN 0 AND 100",
            name="step_up_discount_valid",
        ),
    )

    schedule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("contracts.contract_id", ondelete="CASCADE"),
        nullable=False,
    )
    year_index: Mapped[int] = mapped_column(nullable=False)
    discount_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)


class BillingLedger(Base):
    __tablename__ = "billing_ledger"
    __table_args__ = (
        CheckConstraint(
            "billing_period_end >= billing_period_start",
            name="billing_ledger_period_valid",
        ),
        CheckConstraint(
            "amount_usd >= 0 AND net_amount_usd >= 0 AND vat_amount_usd >= 0",
            name="billing_ledger_amounts_nonnegative",
        ),
        CheckConstraint("fx_rate_applied > 0", name="billing_ledger_fx_positive"),
        Index("ix_billing_ledger_contract_issued", "contract_id", "issued_at"),
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("contracts.contract_id", ondelete="CASCADE"),
        nullable=False,
    )
    billing_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    billing_period_end: Mapped[date] = mapped_column(Date, nullable=False)
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    applied_discount_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
    )
    net_amount_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    vat_amount_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_with_vat_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )
    billed_currency: Mapped[PricingCurrency] = mapped_column(
        pricing_currency_enum,
        nullable=False,
    )
    fx_rate_applied: Mapped[Decimal] = mapped_column(
        Numeric(12, 6),
        nullable=False,
        default=Decimal("1.000000"),
        server_default="1.000000",
    )
    total_billed_local: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    is_paid: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class BillingContact(Base):
    __tablename__ = "billing_contacts"
    __table_args__ = (
        UniqueConstraint("school_id", name="uq_billing_contacts_school_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address_line1: Mapped[str] = mapped_column(String(255), nullable=False)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str] = mapped_column(String(120), nullable=False)
    region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    country: Mapped[str] = mapped_column(String(120), nullable=False)
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
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


class BillingPaymentMethod(Base):
    __tablename__ = "billing_payment_methods"
    __table_args__ = (
        UniqueConstraint("school_id", name="uq_billing_payment_methods_school_id"),
        CheckConstraint("last_four ~ '^[0-9]{4}$'", name="last_four_digits"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
    )
    method_type: Mapped[PaymentMethodType] = mapped_column(
        payment_method_type_enum,
        nullable=False,
    )
    processor_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    processor_payment_method_ref: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_four: Mapped[str] = mapped_column(String(4), nullable=False)
    card_brand: Mapped[str | None] = mapped_column(String(80), nullable=True)
    expiry_month: Mapped[int | None] = mapped_column(nullable=True)
    expiry_year: Mapped[int | None] = mapped_column(nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    account_holder_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
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


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("invoice_number", name="uq_invoices_invoice_number"),
        CheckConstraint("amount >= 0", name="invoice_amount_nonnegative"),
        CheckConstraint(
            "(status = 'paid') = (paid_at IS NOT NULL)",
            name="paid_status_matches_paid_at",
        ),
        Index("ix_invoices_school_issued", "school_id", "issued_at"),
        Index("ix_invoices_school_status_due", "school_id", "status", "due_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    invoice_number: Mapped[str] = mapped_column(String(80), nullable=False)
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
    )
    issued_at: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(invoice_status_enum, nullable=False)
    due_at: Mapped[date] = mapped_column(Date, nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    pdf_url: Mapped[str] = mapped_column(Text, nullable=False)
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
