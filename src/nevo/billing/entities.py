from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from nevo.domain.billing.vocabulary import (
    AccessWindow,
    InvoiceStatus,
    PaymentMethodType,
    PricingCurrency,
    PricingPlan,
    RateType,
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
class PerStudentQuote:
    """What a school owes, derived from its head count and its rate."""

    pricing_plan: PricingPlan
    student_count: int
    per_student_rate: Decimal
    rate_type: RateType
    rate_locked_until: datetime | None
    access_window: AccessWindow
    total_before_vat: Decimal
    vat_rate: Decimal
    vat_amount: Decimal
    total_with_vat: Decimal
    currency: PricingCurrency


@dataclass(frozen=True, slots=True)
class SubscriptionRecord:
    school_id: UUID
    school_name: str
    contract_start: datetime | None
    contract_end: datetime | None
    renewal_banner_visible: bool
    renewal_message: str | None
    billing_contact: BillingContactRecord | None
    payment_method: PaymentMethodRecord | None
    quote: PerStudentQuote


@dataclass(frozen=True, slots=True)
class BankTransferDetails:
    """Where a school sends money when it pays by transfer."""

    bank_name: str
    account_number: str
    account_name: str
    currency: PricingCurrency


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
    currency: PricingCurrency = PricingCurrency.NGN
    # How the amount was reached. Null on anything issued before per-student
    # pricing; a school cannot check a total it cannot see the working for.
    period_label: str | None = None
    student_count: int | None = None
    per_student_rate: Decimal | None = None
    total_before_vat: Decimal | None = None
    vat_amount: Decimal | None = None


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
