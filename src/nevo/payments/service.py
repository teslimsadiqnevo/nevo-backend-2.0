import hashlib
import json
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from nevo.domain.billing.vocabulary import (
    InvoiceStatus,
    PaymentTransactionStatus,
    WebhookEventStatus,
)
from nevo.me.references import is_individual_reference
from nevo.payments.config import PaystackSettings
from nevo.payments.entities import CheckoutSession, PaymentOutcome, ProviderTransaction
from nevo.payments.errors import (
    InvalidWebhookSignatureError,
    InvoiceNotPayableError,
    MissingBillingContactError,
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
        individual_settler: Callable[[ProviderTransaction], Awaitable[PaymentOutcome]]
        | None = None,
    ) -> None:
        self._repository = repository
        self._client = client
        self._settings = settings
        #: /me Phase 4: grants a learner's month for a reference that band
        #: made. Runs only after the checks every event gets above it.
        self._individual_settler = individual_settler

    @property
    def configured(self) -> bool:
        return self._client.configured

    @property
    def client(self) -> PaystackClient:
        return self._client

    @property
    def settings(self) -> PaystackSettings:
        return self._settings

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

    async def recheck_individual(self, reference: str) -> PaymentOutcome:
        """Ask Paystack about a /me purchase and apply the answer.

        The same path the webhook takes after its signature check: the state
        comes from Paystack's API, never from the learner or the redirect.
        For a bank transfer or USSD payment the webhook can arrive minutes
        after the learner is back, and the app needs to say which of waiting,
        done or not through applies meanwhile.
        """
        self._require_configured()
        if not is_individual_reference(reference) or self._individual_settler is None:
            raise PaymentNotFoundError
        provider_transaction = await self._client.verify_transaction(reference)
        return await self._individual_settler(provider_transaction)

    # charge_saved_method was here, and it is gone.
    #
    # It collected an invoice against a school's stored authorization: a
    # charge with nobody present. Lydia's rule of 22 November - no reusable
    # payment token for any customer, and no path that charges a stored
    # instrument with nobody present - removes the whole shape, not just the
    # scheduled job that called it.
    #
    # An invoice is now paid by a person: start_payment for checkout, or
    # confirm_manual_transfer for a bank transfer an administrator has
    # confirmed receiving. Both have somebody present, which is the point.

    async def confirm_manual_transfer(
        self,
        *,
        school_id: UUID,
        invoice_id: UUID,
        bank_reference: str,
        confirmed_by_user_id: UUID,
    ) -> PaymentOutcome:
        """Record a bank transfer an administrator has confirmed receiving.

        Deliberately separate from verify_reference. That one asks Paystack
        whether money arrived; this one is a human asserting it did, for money
        that never went near the processor. Conflating them would mean either
        trusting a payer's claim or asking Paystack about a transaction it has
        never seen.

        Requires no provider configuration - a school can pay by transfer into
        a bank account whether or not card payments are switched on.
        """
        invoice = await self._repository.payable_invoice(
            school_id=school_id,
            invoice_id=invoice_id,
        )
        if invoice is None:
            raise PaymentNotFoundError
        if invoice.status is InvoiceStatus.PAID:
            raise InvoiceNotPayableError

        transaction_id, invoice_paid = await self._repository.record_manual_settlement(
            school_id=school_id,
            invoice_id=invoice_id,
            reference=self._reference(invoice.invoice_number),
            bank_reference=bank_reference.strip(),
            amount=invoice.amount,
            currency=self._client.currency,
            confirmed_by_user_id=confirmed_by_user_id,
            confirmed_at=datetime.now(UTC),
        )
        return PaymentOutcome(
            transaction_id=transaction_id,
            invoice_id=invoice_id,
            reference=bank_reference.strip(),
            status=PaymentTransactionStatus.SUCCESS,
            invoice_paid=invoice_paid,
            payment_method_saved=False,
            message=(
                "Transfer recorded and the invoice is settled."
                if invoice_paid
                else "This transfer reference was already recorded."
            ),
        )

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
            if is_individual_reference(reference):
                if self._individual_settler is None:
                    raise PaymentNotFoundError
                outcome = await self._individual_settler(provider_transaction)
            else:
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
