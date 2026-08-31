import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.billing import (
    BillingContact,
    BillingPaymentMethod,
    Invoice,
    PaymentTransaction,
    PaymentWebhookEvent,
)
from nevo.domain.billing.vocabulary import (
    InvoiceStatus,
    PaymentTransactionStatus,
    PricingCurrency,
    WebhookEventStatus,
)
from nevo.payments.entities import ProviderAuthorization


@dataclass(frozen=True, slots=True)
class PayableInvoice:
    invoice_id: UUID
    school_id: UUID
    invoice_number: str
    amount: Decimal
    status: InvoiceStatus
    billing_email: str | None


@dataclass(frozen=True, slots=True)
class TransactionRecord:
    id: UUID
    school_id: UUID
    invoice_id: UUID | None
    reference: str
    status: PaymentTransactionStatus
    amount: Decimal
    amount_minor: int
    currency: PricingCurrency


@dataclass(frozen=True, slots=True)
class SavedMethod:
    authorization_code: str
    billing_email: str


class SqlAlchemyPaymentRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def payable_invoice(
        self,
        *,
        school_id: UUID,
        invoice_id: UUID,
    ) -> PayableInvoice | None:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(Invoice, BillingContact.email)
                    .outerjoin(BillingContact, BillingContact.school_id == Invoice.school_id)
                    .where(Invoice.id == invoice_id, Invoice.school_id == school_id)
                )
            ).first()
        if row is None:
            return None
        invoice, billing_email = row
        return PayableInvoice(
            invoice_id=invoice.id,
            school_id=invoice.school_id,
            invoice_number=invoice.invoice_number,
            amount=invoice.amount,
            status=invoice.status,
            billing_email=billing_email,
        )

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
        async with self._sessions.begin() as session:
            session.add(
                PaymentTransaction(
                    id=transaction_id,
                    school_id=school_id,
                    invoice_id=invoice_id,
                    reference=reference,
                    amount=amount,
                    amount_minor=amount_minor,
                    currency=currency,
                    initiated_by_user_id=initiated_by_user_id,
                    status=PaymentTransactionStatus.PENDING,
                )
            )
        return transaction_id

    async def set_authorization_url(self, transaction_id: UUID, url: str) -> None:
        async with self._sessions.begin() as session:
            record = await session.get(PaymentTransaction, transaction_id)
            if record is not None:
                record.authorization_url = url

    async def transaction_by_reference(self, reference: str) -> TransactionRecord | None:
        async with self._sessions() as session:
            record = await session.scalar(
                select(PaymentTransaction).where(PaymentTransaction.reference == reference)
            )
        if record is None:
            return None
        return TransactionRecord(
            id=record.id,
            school_id=record.school_id,
            invoice_id=record.invoice_id,
            reference=record.reference,
            status=record.status,
            amount=record.amount,
            amount_minor=record.amount_minor,
            currency=record.currency,
        )

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
        """Apply a processor outcome exactly once.

        Returns ``(invoice_paid, payment_method_saved)``. Re-settling a
        transaction that already succeeded is a no-op, so a duplicated webhook
        and a manual verify cannot mark the same invoice paid twice.
        """
        async with self._sessions.begin() as session:
            record = await session.scalar(
                select(PaymentTransaction)
                .where(PaymentTransaction.reference == reference)
                .with_for_update()
            )
            if record is None or record.status is PaymentTransactionStatus.SUCCESS:
                return False, False
            record.status = status
            record.provider_reference = provider_reference or record.provider_reference
            record.last_error = error
            record.paid_at = (
                (paid_at or datetime.now(UTC))
                if status is PaymentTransactionStatus.SUCCESS
                else None
            )
            if status is not PaymentTransactionStatus.SUCCESS:
                return False, False

            invoice_paid = False
            if record.invoice_id is not None:
                invoice = await session.get(Invoice, record.invoice_id)
                if invoice is not None and invoice.status is not InvoiceStatus.PAID:
                    invoice.status = InvoiceStatus.PAID
                    invoice.paid_at = record.paid_at
                    invoice_paid = True

            method_saved = False
            if authorization is not None and authorization.reusable:
                await self._upsert_payment_method(
                    session,
                    school_id=record.school_id,
                    authorization=authorization,
                    customer_code=customer_code,
                    actor_user_id=record.initiated_by_user_id,
                )
                method_saved = True
            return invoice_paid, method_saved

    @staticmethod
    async def _upsert_payment_method(
        session: AsyncSession,
        *,
        school_id: UUID,
        authorization: ProviderAuthorization,
        customer_code: str | None,
        actor_user_id: UUID | None,
    ) -> None:
        existing = await session.scalar(
            select(BillingPaymentMethod).where(BillingPaymentMethod.school_id == school_id)
        )
        updated_by = actor_user_id or (existing.updated_by_user_id if existing else None)
        if updated_by is None:
            # The column is NOT NULL and there is no actor to attribute the
            # change to, so leave the stored method alone rather than fail the
            # settlement of a payment that already succeeded.
            return
        display_name = (
            f"{authorization.card_brand or authorization.bank_name or 'Card'} "
            f"ending {authorization.last_four}"
        ).strip()
        if existing is None:
            session.add(
                BillingPaymentMethod(
                    school_id=school_id,
                    method_type=authorization.method_type,
                    processor_name="paystack",
                    processor_payment_method_ref=authorization.authorization_code,
                    processor_customer_code=customer_code,
                    display_name=display_name,
                    last_four=authorization.last_four,
                    card_brand=authorization.card_brand,
                    expiry_month=authorization.expiry_month,
                    expiry_year=authorization.expiry_year,
                    bank_name=authorization.bank_name,
                    account_holder_name=authorization.account_name,
                    is_reusable=authorization.reusable,
                    updated_by_user_id=updated_by,
                )
            )
            return
        existing.method_type = authorization.method_type
        existing.processor_name = "paystack"
        existing.processor_payment_method_ref = authorization.authorization_code
        existing.processor_customer_code = customer_code or existing.processor_customer_code
        existing.display_name = display_name
        existing.last_four = authorization.last_four
        existing.card_brand = authorization.card_brand
        existing.expiry_month = authorization.expiry_month
        existing.expiry_year = authorization.expiry_year
        existing.bank_name = authorization.bank_name
        existing.account_holder_name = authorization.account_name
        existing.is_reusable = authorization.reusable
        existing.updated_by_user_id = updated_by

    async def saved_method(self, school_id: UUID) -> SavedMethod | None:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(
                        BillingPaymentMethod.processor_payment_method_ref,
                        BillingContact.email,
                    )
                    .join(
                        BillingContact,
                        BillingContact.school_id == BillingPaymentMethod.school_id,
                    )
                    .where(
                        BillingPaymentMethod.school_id == school_id,
                        BillingPaymentMethod.is_reusable.is_(True),
                        BillingPaymentMethod.processor_payment_method_ref.is_not(None),
                    )
                )
            ).first()
        if row is None:
            return None
        authorization_code, email = row
        if not authorization_code or not email:
            return None
        return SavedMethod(authorization_code=authorization_code, billing_email=email)

    async def claim_webhook_event(
        self,
        *,
        event_key: str,
        event_type: str,
        payload: dict[str, Any],
        provider: str = "paystack",
    ) -> bool:
        """Record the event; return False when it has already been seen."""
        async with self._sessions.begin() as session:
            statement = (
                insert(PaymentWebhookEvent)
                .values(
                    provider=provider,
                    event_key=event_key,
                    event_type=event_type,
                    payload=json.loads(json.dumps(payload, default=str)),
                    status=WebhookEventStatus.RECEIVED,
                )
                .on_conflict_do_nothing(constraint="uq_payment_webhook_events_provider_key")
                .returning(PaymentWebhookEvent.id)
            )
            return await session.scalar(statement) is not None

    async def finish_webhook_event(
        self,
        *,
        event_key: str,
        status: WebhookEventStatus,
        error: str | None = None,
        provider: str = "paystack",
    ) -> None:
        async with self._sessions.begin() as session:
            record = await session.scalar(
                select(PaymentWebhookEvent).where(
                    PaymentWebhookEvent.provider == provider,
                    PaymentWebhookEvent.event_key == event_key,
                )
            )
            if record is not None:
                record.status = status
                record.last_error = error
                record.processed_at = datetime.now(UTC)
