"""Payment reconciliation tests — the money-safety rules."""
import hashlib
import hmac
import json
from decimal import Decimal

import pytest
from pydantic import SecretStr

from nevo.domain.billing.vocabulary import InvoiceStatus, PaymentTransactionStatus
from nevo.payments.config import PaystackSettings
from nevo.payments.errors import (
    InvalidWebhookSignatureError,
    InvoiceNotPayableError,
    MissingBillingContactError,
    NoReusablePaymentMethodError,
    PaymentNotFoundError,
    PaymentProviderUnavailableError,
)
from nevo.payments.repositories import SavedMethod
from nevo.payments.service import PaymentService
from tests.payments.fakes import (
    ACTOR_ID,
    INVOICE_ID,
    SCHOOL_ID,
    FakePaymentRepository,
    FakePaystackClient,
    payable_invoice,
    provider_transaction,
)

SECRET = "sk_test_secret"


def _service(
    repository: FakePaymentRepository,
    client: FakePaystackClient,
) -> PaymentService:
    return PaymentService(
        repository=repository,  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
        settings=PaystackSettings(PAYSTACK_SECRET_KEY=SecretStr(SECRET)),  # type: ignore[call-arg]
    )


def _signed(body: dict[str, object]) -> tuple[bytes, str]:
    payload = json.dumps(body).encode()
    return payload, hmac.new(SECRET.encode(), payload, hashlib.sha512).hexdigest()


async def test_unconfigured_provider_refuses_checkout() -> None:
    service = _service(FakePaymentRepository(), FakePaystackClient(configured=False))

    with pytest.raises(PaymentProviderUnavailableError):
        await service.start_invoice_payment(
            school_id=SCHOOL_ID, invoice_id=INVOICE_ID, actor_user_id=ACTOR_ID
        )


async def test_checkout_creates_a_pending_transaction() -> None:
    repository = FakePaymentRepository(invoice=payable_invoice())
    client = FakePaystackClient()
    service = _service(repository, client)

    session = await service.start_invoice_payment(
        school_id=SCHOOL_ID, invoice_id=INVOICE_ID, actor_user_id=ACTOR_ID
    )

    assert session.authorization_url == "https://checkout.paystack.com/abc"
    assert session.amount == Decimal("1250.00")
    assert repository.transactions[session.reference].amount_minor == 125_000
    assert client.initialized[0]["email"] == "bursar@school.test"
    assert client.initialized[0]["metadata"]["invoice_id"] == str(INVOICE_ID)


async def test_checkout_rejects_an_already_paid_invoice() -> None:
    repository = FakePaymentRepository(invoice=payable_invoice(status=InvoiceStatus.PAID))
    service = _service(repository, FakePaystackClient())

    with pytest.raises(InvoiceNotPayableError):
        await service.start_invoice_payment(
            school_id=SCHOOL_ID, invoice_id=INVOICE_ID, actor_user_id=ACTOR_ID
        )


async def test_checkout_requires_a_billing_email() -> None:
    repository = FakePaymentRepository(invoice=payable_invoice(billing_email=None))
    service = _service(repository, FakePaystackClient())

    with pytest.raises(MissingBillingContactError):
        await service.start_invoice_payment(
            school_id=SCHOOL_ID, invoice_id=INVOICE_ID, actor_user_id=ACTOR_ID
        )


async def test_unknown_invoice_is_not_found() -> None:
    service = _service(FakePaymentRepository(), FakePaystackClient())

    with pytest.raises(PaymentNotFoundError):
        await service.start_invoice_payment(
            school_id=SCHOOL_ID, invoice_id=INVOICE_ID, actor_user_id=ACTOR_ID
        )


async def test_verify_marks_the_invoice_paid() -> None:
    repository = FakePaymentRepository(invoice=payable_invoice())
    client = FakePaystackClient()
    service = _service(repository, client)
    session = await service.start_invoice_payment(
        school_id=SCHOOL_ID, invoice_id=INVOICE_ID, actor_user_id=ACTOR_ID
    )
    client.transaction = provider_transaction(reference=session.reference)

    outcome = await service.verify_reference(session.reference)

    assert outcome.status is PaymentTransactionStatus.SUCCESS
    assert outcome.invoice_paid is True
    assert outcome.payment_method_saved is True


async def test_verify_is_idempotent() -> None:
    repository = FakePaymentRepository(invoice=payable_invoice())
    client = FakePaystackClient()
    service = _service(repository, client)
    session = await service.start_invoice_payment(
        school_id=SCHOOL_ID, invoice_id=INVOICE_ID, actor_user_id=ACTOR_ID
    )
    client.transaction = provider_transaction(reference=session.reference)

    first = await service.verify_reference(session.reference)
    second = await service.verify_reference(session.reference)

    assert first.invoice_paid is True
    assert second.invoice_paid is False
    assert second.message == "This payment was already settled."


async def test_amount_mismatch_never_grants_value() -> None:
    """A success callback for the wrong amount must not clear the invoice."""
    repository = FakePaymentRepository(invoice=payable_invoice())
    client = FakePaystackClient()
    service = _service(repository, client)
    session = await service.start_invoice_payment(
        school_id=SCHOOL_ID, invoice_id=INVOICE_ID, actor_user_id=ACTOR_ID
    )
    client.transaction = provider_transaction(reference=session.reference, amount_minor=100)

    outcome = await service.verify_reference(session.reference)

    assert outcome.status is PaymentTransactionStatus.FAILED
    assert outcome.invoice_paid is False
    assert "did not match" in outcome.message


async def test_currency_mismatch_never_grants_value() -> None:
    repository = FakePaymentRepository(invoice=payable_invoice())
    client = FakePaystackClient()
    service = _service(repository, client)
    session = await service.start_invoice_payment(
        school_id=SCHOOL_ID, invoice_id=INVOICE_ID, actor_user_id=ACTOR_ID
    )
    client.transaction = provider_transaction(reference=session.reference, currency="USD")

    outcome = await service.verify_reference(session.reference)

    assert outcome.status is PaymentTransactionStatus.FAILED
    assert outcome.invoice_paid is False


async def test_failed_transaction_leaves_the_invoice_open() -> None:
    repository = FakePaymentRepository(invoice=payable_invoice())
    client = FakePaystackClient()
    service = _service(repository, client)
    session = await service.start_invoice_payment(
        school_id=SCHOOL_ID, invoice_id=INVOICE_ID, actor_user_id=ACTOR_ID
    )
    client.transaction = provider_transaction(
        reference=session.reference,
        status=PaymentTransactionStatus.FAILED,
        gateway_message="Insufficient funds",
    )

    outcome = await service.verify_reference(session.reference)

    assert outcome.status is PaymentTransactionStatus.FAILED
    assert outcome.invoice_paid is False
    assert outcome.message == "Insufficient funds"


async def test_webhook_rejects_a_bad_signature() -> None:
    service = _service(FakePaymentRepository(), FakePaystackClient())
    payload = json.dumps({"event": "charge.success"}).encode()

    with pytest.raises(InvalidWebhookSignatureError):
        await service.handle_webhook(payload=payload, signature="deadbeef")


async def test_webhook_settles_and_then_deduplicates() -> None:
    repository = FakePaymentRepository(invoice=payable_invoice())
    client = FakePaystackClient()
    service = _service(repository, client)
    session = await service.start_invoice_payment(
        school_id=SCHOOL_ID, invoice_id=INVOICE_ID, actor_user_id=ACTOR_ID
    )
    client.transaction = provider_transaction(reference=session.reference)
    payload, signature = _signed(
        {
            "event": "charge.success",
            "data": {"id": 998877, "reference": session.reference},
        }
    )

    first = await service.handle_webhook(payload=payload, signature=signature)
    second = await service.handle_webhook(payload=payload, signature=signature)

    assert first is not None
    assert first.invoice_paid is True
    assert second is None, "a replayed webhook must not be applied twice"


async def test_webhook_ignores_unrelated_events() -> None:
    repository = FakePaymentRepository(invoice=payable_invoice())
    service = _service(repository, FakePaystackClient())
    payload, signature = _signed(
        {"event": "customer.identification.failed", "data": {"id": 1, "reference": "x"}}
    )

    assert await service.handle_webhook(payload=payload, signature=signature) is None
    assert repository.webhook_events


async def test_webhook_re_verifies_rather_than_trusting_the_body() -> None:
    """The callback body is untrusted input; the amount comes from the API."""
    repository = FakePaymentRepository(invoice=payable_invoice())
    client = FakePaystackClient()
    service = _service(repository, client)
    session = await service.start_invoice_payment(
        school_id=SCHOOL_ID, invoice_id=INVOICE_ID, actor_user_id=ACTOR_ID
    )
    client.transaction = provider_transaction(reference=session.reference, amount_minor=1)
    payload, signature = _signed(
        {
            "event": "charge.success",
            "data": {"id": 1, "reference": session.reference, "amount": 125_000},
        }
    )

    outcome = await service.handle_webhook(payload=payload, signature=signature)

    assert client.verified == [session.reference]
    assert outcome is not None
    assert outcome.invoice_paid is False


async def test_charge_saved_method_requires_a_stored_authorization() -> None:
    repository = FakePaymentRepository(invoice=payable_invoice())
    service = _service(repository, FakePaystackClient())

    with pytest.raises(NoReusablePaymentMethodError):
        await service.charge_saved_method(school_id=SCHOOL_ID, invoice_id=INVOICE_ID)


async def test_charge_saved_method_collects_and_settles() -> None:
    repository = FakePaymentRepository(
        invoice=payable_invoice(),
        method=SavedMethod(
            authorization_code="AUTH_abc123",
            billing_email="bursar@school.test",
        ),
    )
    client = FakePaystackClient()
    service = _service(repository, client)

    def charge(**kwargs: object):  # type: ignore[no-untyped-def]
        client.charged.append(kwargs)
        client.transaction = provider_transaction(reference=str(kwargs["reference"]))
        return client.transaction

    async def charge_authorization(**kwargs: object):  # type: ignore[no-untyped-def]
        return charge(**kwargs)

    client.charge_authorization = charge_authorization  # type: ignore[method-assign]

    outcome = await service.charge_saved_method(school_id=SCHOOL_ID, invoice_id=INVOICE_ID)

    assert outcome.status is PaymentTransactionStatus.SUCCESS
    assert outcome.invoice_paid is True
    assert client.charged[0]["authorization_code"] == "AUTH_abc123"
