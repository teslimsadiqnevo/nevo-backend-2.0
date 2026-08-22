import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
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
    InvoiceStatus,
    PaymentMethodType,
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
