import hashlib
import json
import secrets
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from nevo.domain.billing.vocabulary import (
    InvoiceStatus,
    PaymentTransactionStatus,
    WebhookEventStatus,
)
from nevo.payments.config import PaystackSettings
from nevo.payments.entities import CheckoutSession, PaymentOutcome, ProviderTransaction
from nevo.payments.errors import (
    InvalidWebhookSignatureError,
    InvoiceNotPayableError,
    MissingBillingContactError,
    NoReusablePaymentMethodError,
    PaymentNotFoundError,
    PaymentProviderUnavailableError,
)
from nevo.payments.paystack import (
    PaystackClient,
    to_minor_units,
    verify_webhook_signature,
)
from nevo.payments.repositories import SqlAlchemyPaymentRepository

SETTLED_EVENTS = frozenset({"charge.success"})
FAILURE_EVENTS = frozenset({"charge.failed", "invoice.payment_failed"})


class PaymentService:
    """Collects money for invoices through Paystack and reconciles the result."""

    def __init__(
        self,
        *,
        repository: SqlAlchemyPaymentRepository,
        client: PaystackClient,
        settings: PaystackSettings,
    ) -> None:
        self._repository = repository
        self._client = client
        self._settings = settings

    @property
    def configured(self) -> bool:
        return self._client.configured

    async def start_invoice_payment(
        self,
        *,
        school_id: UUID,
        invoice_id: UUID,
        actor_user_id: UUID | None,
    ) -> CheckoutSession:
        """Open a hosted checkout for an outstanding invoice."""
        self._require_configured()
        invoice = await self._repository.payable_invoice(
            school_id=school_id,
            invoice_id=invoice_id,
        )
        if invoice is None:
            raise PaymentNotFoundError
        if invoice.status is InvoiceStatus.PAID:
            raise InvoiceNotPayableError
        if not invoice.billing_email:
            raise MissingBillingContactError

        reference = self._reference(invoice.invoice_number)
        currency = self._client.currency
        transaction_id = await self._repository.create_transaction(
            school_id=school_id,
            invoice_id=invoice_id,
            reference=reference,
            amount=invoice.amount,
            amount_minor=to_minor_units(invoice.amount),
            currency=currency,
            initiated_by_user_id=actor_user_id,
        )
        authorization_url = await self._client.initialize_transaction(
            email=invoice.billing_email,
            amount=invoice.amount,
            reference=reference,
            currency=currency,
            metadata={
                "school_id": str(school_id),
                "invoice_id": str(invoice_id),
                "invoice_number": invoice.invoice_number,
            },
        )
        await self._repository.set_authorization_url(transaction_id, authorization_url)
        return CheckoutSession(
            transaction_id=transaction_id,
            invoice_id=invoice_id,
            reference=reference,
            authorization_url=authorization_url,
            amount=invoice.amount,
            currency=currency,
        )

    async def verify_reference(self, reference: str) -> PaymentOutcome:
        """Confirm a transaction with Paystack and apply it to the invoice."""
        self._require_configured()
        transaction = await self._repository.transaction_by_reference(reference)
        if transaction is None:
            raise PaymentNotFoundError
        provider_transaction = await self._client.verify_transaction(reference)
        return await self._settle(provider_transaction)

    async def charge_saved_method(
        self,
        *,
        school_id: UUID,
        invoice_id: UUID,
    ) -> PaymentOutcome:
        """Collect an invoice against the school's stored authorization."""
        self._require_configured()
        invoice = await self._repository.payable_invoice(
            school_id=school_id,
            invoice_id=invoice_id,
        )
        if invoice is None:
            raise PaymentNotFoundError
        if invoice.status is InvoiceStatus.PAID:
            raise InvoiceNotPayableError
        method = await self._repository.saved_method(school_id)
        if method is None:
            raise NoReusablePaymentMethodError

        reference = self._reference(invoice.invoice_number)
        currency = self._client.currency
        await self._repository.create_transaction(
            school_id=school_id,
            invoice_id=invoice_id,
            reference=reference,
            amount=invoice.amount,
            amount_minor=to_minor_units(invoice.amount),
            currency=currency,
            initiated_by_user_id=None,
        )
        provider_transaction = await self._client.charge_authorization(
            email=method.billing_email,
            amount=invoice.amount,
            reference=reference,
            authorization_code=method.authorization_code,
            currency=currency,
        )
        return await self._settle(provider_transaction)

    async def handle_webhook(
        self,
        *,
        payload: bytes,
        signature: str | None,
    ) -> PaymentOutcome | None:
        """Verify, de-duplicate, and apply one processor callback."""
        self._require_configured()
        if not verify_webhook_signature(
            payload=payload,
            signature=signature,
            secret=self._client.secret(),
        ):
            raise InvalidWebhookSignatureError
        try:
            body: Any = json.loads(payload)
        except ValueError as error:
            raise InvalidWebhookSignatureError from error
        if not isinstance(body, dict):
            raise InvalidWebhookSignatureError

        event_type = str(body.get("event") or "unknown")
        raw_data = body.get("data")
        data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
        reference = str(data.get("reference") or "")
        event_key = self._event_key(event_type, data, payload)

        claimed = await self._repository.claim_webhook_event(
            event_key=event_key,
            event_type=event_type,
            payload=body,
        )
        if not claimed:
            return None
        if event_type not in SETTLED_EVENTS | FAILURE_EVENTS or not reference:
            await self._repository.finish_webhook_event(
                event_key=event_key,
                status=WebhookEventStatus.IGNORED,
            )
            return None

        try:
            # Re-verify against the API rather than trusting the callback body.
            provider_transaction = await self._client.verify_transaction(reference)
            outcome = await self._settle(provider_transaction)
        except Exception as error:
            await self._repository.finish_webhook_event(
                event_key=event_key,
                status=WebhookEventStatus.FAILED,
                error=str(error)[:1000],
            )
            raise
        await self._repository.finish_webhook_event(
            event_key=event_key,
            status=WebhookEventStatus.PROCESSED,
        )
        return outcome

    async def _settle(self, provider_transaction: ProviderTransaction) -> PaymentOutcome:
        transaction = await self._repository.transaction_by_reference(
            provider_transaction.reference
        )
        if transaction is None:
            raise PaymentNotFoundError
        if transaction.status is PaymentTransactionStatus.SUCCESS:
            return PaymentOutcome(
                transaction_id=transaction.id,
                invoice_id=transaction.invoice_id,
                reference=transaction.reference,
                status=PaymentTransactionStatus.SUCCESS,
                invoice_paid=False,
                payment_method_saved=False,
                message="This payment was already settled.",
            )

        status = provider_transaction.status
        error: str | None = provider_transaction.gateway_message
        if status is PaymentTransactionStatus.SUCCESS and not self._amount_matches(
            expected_minor=transaction.amount_minor,
            expected_currency=transaction.currency.value,
            provider_transaction=provider_transaction,
        ):
            # Never grant value for an amount or currency we did not ask for.
            status = PaymentTransactionStatus.FAILED
            error = (
                "Provider amount did not match the invoice: expected "
                f"{transaction.amount_minor} {transaction.currency.value}, got "
                f"{provider_transaction.amount_minor} {provider_transaction.currency}"
            )

        invoice_paid, method_saved = await self._repository.settle(
            reference=transaction.reference,
            status=status,
            provider_reference=provider_transaction.provider_reference,
            paid_at=provider_transaction.paid_at,
            error=None if status is PaymentTransactionStatus.SUCCESS else error,
            authorization=provider_transaction.authorization,
            customer_code=None,
        )
        return PaymentOutcome(
            transaction_id=transaction.id,
            invoice_id=transaction.invoice_id,
            reference=transaction.reference,
            status=status,
            invoice_paid=invoice_paid,
            payment_method_saved=method_saved,
            message=(
                "Payment confirmed."
                if status is PaymentTransactionStatus.SUCCESS
                else (error or "The payment was not completed.")
            ),
        )

    @staticmethod
    def _amount_matches(
        *,
        expected_minor: int,
        expected_currency: str,
        provider_transaction: ProviderTransaction,
    ) -> bool:
        if provider_transaction.amount_minor != expected_minor:
            return False
        provider_currency = provider_transaction.currency.strip().upper()
        return not provider_currency or provider_currency == expected_currency.upper()

    @staticmethod
    def _event_key(event_type: str, data: dict[str, Any], payload: bytes) -> str:
        """A stable per-event identity so retries are not applied twice."""
        provider_id = data.get("id")
        reference = data.get("reference")
        if provider_id:
            return f"{event_type}:{provider_id}"
        if reference:
            return f"{event_type}:{reference}"
        return f"{event_type}:{hashlib.sha256(payload).hexdigest()}"

    @staticmethod
    def _reference(invoice_number: str) -> str:
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        slug = "".join(char for char in invoice_number if char.isalnum())[:40]
        return f"nevo-{slug}-{stamp}-{secrets.token_hex(4)}"

    def _require_configured(self) -> None:
        if not self.configured:
            raise PaymentProviderUnavailableError
