"""In-memory doubles for payment reconciliation tests."""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from nevo.domain.billing.vocabulary import (
    InvoiceStatus,
    PaymentMethodType,
    PaymentTransactionStatus,
    PricingCurrency,
    WebhookEventStatus,
)
from nevo.payments.entities import ProviderAuthorization, ProviderTransaction
from nevo.payments.repositories import PayableInvoice, SavedMethod, TransactionRecord

SCHOOL_ID = UUID("22222222-2222-2222-2222-222222222222")
INVOICE_ID = UUID("33333333-3333-3333-3333-333333333333")
ACTOR_ID = UUID("44444444-4444-4444-4444-444444444444")


@dataclass
class FakePaymentRepository:
    invoice: PayableInvoice | None = None
    method: SavedMethod | None = None
    transactions: dict[str, TransactionRecord] = field(default_factory=dict)
    settlements: list[dict[str, Any]] = field(default_factory=list)
    webhook_events: dict[str, WebhookEventStatus] = field(default_factory=dict)
    invoice_paid: bool = False

    async def payable_invoice(
        self, *, school_id: UUID, invoice_id: UUID
    ) -> PayableInvoice | None:
        if self.invoice is None:
            return None
        if self.invoice.school_id != school_id or self.invoice.invoice_id != invoice_id:
            return None
        return self.invoice

    async def create_transaction(
        self,
        *,
        school_id: UUID,
        invoice_id: UUID,
        reference: str,
        amount: Decimal,
        amount_minor: int,
        currency: PricingCurrency,
        initiated_by_user_id: UUID | None,
    ) -> UUID:
        transaction_id = uuid4()
        self.transactions[reference] = TransactionRecord(
            id=transaction_id,
            school_id=school_id,
            invoice_id=invoice_id,
            reference=reference,
            status=PaymentTransactionStatus.PENDING,
            amount=amount,
            amount_minor=amount_minor,
            currency=currency,
        )
        return transaction_id

    async def set_authorization_url(self, transaction_id: UUID, url: str) -> None:
        return None

    async def transaction_by_reference(self, reference: str) -> TransactionRecord | None:
        return self.transactions.get(reference)

    async def settle(
        self,
        *,
        reference: str,
        status: PaymentTransactionStatus,
        provider_reference: str | None,
        paid_at: datetime | None,
        error: str | None,
        authorization: ProviderAuthorization | None,
        customer_code: str | None,
    ) -> tuple[bool, bool]:
        self.settlements.append({"reference": reference, "status": status, "error": error})
        current = self.transactions.get(reference)
        if current is None or current.status is PaymentTransactionStatus.SUCCESS:
            return False, False
        self.transactions[reference] = TransactionRecord(
            id=current.id,
            school_id=current.school_id,
            invoice_id=current.invoice_id,
            reference=current.reference,
            status=status,
            amount=current.amount,
            amount_minor=current.amount_minor,
            currency=current.currency,
        )
        if status is not PaymentTransactionStatus.SUCCESS:
            return False, False
        paid = not self.invoice_paid
        self.invoice_paid = True
        return paid, bool(authorization and authorization.reusable)

    async def saved_method(self, school_id: UUID) -> SavedMethod | None:
        return self.method

    async def claim_webhook_event(
        self,
        *,
        event_key: str,
        event_type: str,
        payload: dict[str, Any],
        provider: str = "paystack",
    ) -> bool:
        if event_key in self.webhook_events:
            return False
        self.webhook_events[event_key] = WebhookEventStatus.RECEIVED
        return True

    async def finish_webhook_event(
        self,
        *,
        event_key: str,
        status: WebhookEventStatus,
        error: str | None = None,
        provider: str = "paystack",
    ) -> None:
        self.webhook_events[event_key] = status


@dataclass
class FakePaystackClient:
    configured: bool = True
    currency: PricingCurrency = PricingCurrency.NGN
    authorization_url: str = "https://checkout.paystack.com/abc"
    transaction: ProviderTransaction | None = None
    initialized: list[dict[str, Any]] = field(default_factory=list)
    charged: list[dict[str, Any]] = field(default_factory=list)
    verified: list[str] = field(default_factory=list)

    def secret(self) -> str:
        return "sk_test_secret"

    async def initialize_transaction(self, **kwargs: Any) -> str:
        self.initialized.append(kwargs)
        return self.authorization_url

    async def verify_transaction(self, reference: str) -> ProviderTransaction:
        self.verified.append(reference)
        assert self.transaction is not None
        return self.transaction

    async def charge_authorization(self, **kwargs: Any) -> ProviderTransaction:
        self.charged.append(kwargs)
        assert self.transaction is not None
        return self.transaction


def payable_invoice(
    *,
    amount: Decimal = Decimal("1250.00"),
    status: InvoiceStatus = InvoiceStatus.PENDING,
    billing_email: str | None = "bursar@school.test",
) -> PayableInvoice:
    return PayableInvoice(
        invoice_id=INVOICE_ID,
        school_id=SCHOOL_ID,
        invoice_number="INV-001",
        amount=amount,
        status=status,
        billing_email=billing_email,
    )


def provider_transaction(
    *,
    reference: str,
    status: PaymentTransactionStatus = PaymentTransactionStatus.SUCCESS,
    amount_minor: int = 125_000,
    currency: str = "NGN",
    reusable: bool = True,
    gateway_message: str | None = None,
) -> ProviderTransaction:
    return ProviderTransaction(
        reference=reference,
        status=status,
        amount_minor=amount_minor,
        currency=currency,
        provider_reference="998877",
        paid_at=None,
        customer_email="bursar@school.test",
        authorization=ProviderAuthorization(
            authorization_code="AUTH_abc123",
            method_type=PaymentMethodType.CARD,
            last_four="4081",
            card_brand="visa",
            bank_name=None,
            expiry_month=12,
            expiry_year=2030,
            account_name=None,
            reusable=reusable,
        ),
        gateway_message=gateway_message,
    )
