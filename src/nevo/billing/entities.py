from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from nevo.domain.accounts.vocabulary import SchoolEnrollmentBand
from nevo.domain.billing.vocabulary import (
    InvoiceStatus,
    PaymentMethodType,
    PricingCurrency,
    SubscriptionTier,
)


@dataclass(frozen=True, slots=True)
class BillingContactRecord:
    id: UUID
    email: str
    phone: str | None
    address_line1: str
    address_line2: str | None
    city: str
    region: str | None
    postal_code: str | None
    country: str


@dataclass(frozen=True, slots=True)
class PaymentMethodRecord:
    id: UUID
    method_type: PaymentMethodType
    display_name: str
    last_four: str
    card_brand: str | None
    expiry_month: int | None
    expiry_year: int | None
    bank_name: str | None
    account_holder_name: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SubscriptionRecord:
    school_id: UUID
    school_name: str
    subscription_tier: SubscriptionTier | None
    student_count_band: SchoolEnrollmentBand | None
    contract_value: Decimal | None
    contract_start: datetime | None
    contract_end: datetime | None
    renewal_banner_visible: bool
    renewal_message: str | None
    billing_contact: BillingContactRecord | None
    payment_method: PaymentMethodRecord | None


@dataclass(frozen=True, slots=True)
class InvoiceRecord:
    id: UUID
    invoice_number: str
    issued_at: date
    amount: Decimal
    status: InvoiceStatus
    due_at: date
    paid_at: datetime | None
    pdf_url: str


@dataclass(frozen=True, slots=True)
class UpcomingCharge:
    invoice_id: UUID | None
    invoice_number: str | None
    due_at: date | None
    amount: Decimal | None
    status: InvoiceStatus | None
    renewal_banner_visible: bool
    renewal_message: str | None


@dataclass(frozen=True, slots=True)
class PaymentMethodUpdate:
    method_type: PaymentMethodType
    display_name: str
    last_four: str
    processor_name: str | None = None
    processor_payment_method_ref: str | None = None
    card_brand: str | None = None
    expiry_month: int | None = None
    expiry_year: int | None = None
    bank_name: str | None = None
    account_holder_name: str | None = None


@dataclass(frozen=True, slots=True)
class BillingContactUpdate:
    email: str
    phone: str | None
    address_line1: str
    address_line2: str | None
    city: str
    region: str | None
    postal_code: str | None
    country: str


@dataclass(frozen=True, slots=True)
class BillingLedgerQuote:
    tier: SubscriptionTier
    amount_usd: Decimal
    applied_discount_percent: Decimal
    net_amount_usd: Decimal
    vat_amount_usd: Decimal
    total_with_vat_usd: Decimal
    billed_currency: PricingCurrency
    fx_rate_applied: Decimal
    total_billed_local: Decimal
