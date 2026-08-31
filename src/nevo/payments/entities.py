from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from nevo.domain.billing.vocabulary import (
    PaymentMethodType,
    PaymentTransactionStatus,
    PricingCurrency,
)


@dataclass(frozen=True, slots=True)
class CheckoutSession:
    """What the frontend needs to send a payer to Paystack."""

    transaction_id: UUID
    invoice_id: UUID
    reference: str
    authorization_url: str
    amount: Decimal
    currency: PricingCurrency


@dataclass(frozen=True, slots=True)
class ProviderAuthorization:
    """A reusable payment instrument returned by the processor."""

    authorization_code: str
    method_type: PaymentMethodType
    last_four: str
    card_brand: str | None
    bank_name: str | None
    expiry_month: int | None
    expiry_year: int | None
    account_name: str | None
    reusable: bool


@dataclass(frozen=True, slots=True)
class ProviderTransaction:
    """The processor's view of one transaction."""

    reference: str
    status: PaymentTransactionStatus
    amount_minor: int
    currency: str
    provider_reference: str | None
    paid_at: datetime | None
    customer_email: str | None
    authorization: ProviderAuthorization | None
    gateway_message: str | None


@dataclass(frozen=True, slots=True)
class PaymentOutcome:
    """The result of reconciling a transaction against an invoice."""

    transaction_id: UUID
    invoice_id: UUID | None
    reference: str
    status: PaymentTransactionStatus
    invoice_paid: bool
    payment_method_saved: bool
    message: str
