"""Paystack client and signature tests."""
import hashlib
import hmac
import json
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

from nevo.domain.billing.vocabulary import (
    PaymentMethodType,
    PaymentTransactionStatus,
    PricingCurrency,
)
from nevo.payments.config import PaystackSettings
from nevo.payments.errors import (
    PaymentProviderRejectedError,
    PaymentProviderUnavailableError,
)
from nevo.payments.paystack import (
    PaystackClient,
    from_minor_units,
    to_minor_units,
    verify_webhook_signature,
)

SECRET = "sk_test_secret"


def _settings(**overrides: object) -> PaystackSettings:
    values: dict[str, object] = {"PAYSTACK_SECRET_KEY": SecretStr(SECRET)}
    values.update(overrides)
    return PaystackSettings(**values)  # type: ignore[arg-type]


def _install(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx.Request]:
    requests: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    transport = httpx.MockTransport(recording)
    original_client = httpx.AsyncClient

    def client(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return requests


def test_minor_unit_conversion_round_trips() -> None:
    assert to_minor_units(Decimal("1250.00")) == 125_000
    assert to_minor_units(Decimal("0.005")) == 1
    assert from_minor_units(125_000) == Decimal("1250.00")


def test_signature_accepts_a_correct_hmac() -> None:
    payload = b'{"event":"charge.success"}'
    signature = hmac.new(SECRET.encode(), payload, hashlib.sha512).hexdigest()

    assert verify_webhook_signature(payload=payload, signature=signature, secret=SECRET)


def test_signature_rejects_tampering_and_absence() -> None:
    payload = b'{"event":"charge.success"}'
    signature = hmac.new(SECRET.encode(), payload, hashlib.sha512).hexdigest()

    assert not verify_webhook_signature(
        payload=b'{"event":"charge.failed"}', signature=signature, secret=SECRET
    )
    assert not verify_webhook_signature(payload=payload, signature=None, secret=SECRET)
    assert not verify_webhook_signature(payload=payload, signature="deadbeef", secret=SECRET)
    assert not verify_webhook_signature(
        payload=payload, signature=signature, secret="another-secret"
    )


def test_client_is_unconfigured_without_a_secret_key() -> None:
    assert not PaystackClient(PaystackSettings()).configured
    assert PaystackClient(_settings()).configured


async def test_unconfigured_client_refuses_to_call() -> None:
    with pytest.raises(PaymentProviderUnavailableError):
        await PaystackClient(PaystackSettings()).verify_transaction("ref")


async def test_initialize_sends_minor_units_and_returns_the_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _install(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "status": True,
                "data": {
                    "authorization_url": "https://checkout.paystack.com/abc",
                    "reference": "nevo-1",
                },
            },
        ),
    )

    url = await PaystackClient(_settings()).initialize_transaction(
        email="bursar@school.test",
        amount=Decimal("1250.00"),
        reference="nevo-1",
        currency=PricingCurrency.NGN,
    )

    assert url == "https://checkout.paystack.com/abc"
    body = json.loads(requests[0].content)
    assert body["amount"] == 125_000
    assert body["currency"] == "NGN"
    assert body["reference"] == "nevo-1"
    assert requests[0].headers["Authorization"] == f"Bearer {SECRET}"


async def test_verify_parses_a_successful_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "status": True,
                "data": {
                    "reference": "nevo-1",
                    "status": "success",
                    "amount": 125_000,
                    "currency": "NGN",
                    "id": 998877,
                    "paid_at": "2026-08-31T10:00:00Z",
                    "gateway_response": "Successful",
                    "customer": {"email": "bursar@school.test"},
                    "authorization": {
                        "authorization_code": "AUTH_abc123",
                        "last4": "4081",
                        "card_type": "visa",
                        "bank": "Test Bank",
                        "exp_month": "12",
                        "exp_year": "2030",
                        "channel": "card",
                        "reusable": True,
                    },
                },
            },
        ),
    )

    result = await PaystackClient(_settings()).verify_transaction("nevo-1")

    assert result.status is PaymentTransactionStatus.SUCCESS
    assert result.amount_minor == 125_000
    assert result.currency == "NGN"
    assert result.provider_reference == "998877"
    assert result.paid_at is not None
    assert result.customer_email == "bursar@school.test"
    assert result.authorization is not None
    assert result.authorization.authorization_code == "AUTH_abc123"
    assert result.authorization.method_type is PaymentMethodType.CARD
    assert result.authorization.expiry_month == 12
    assert result.authorization.reusable is True


async def test_verify_maps_a_failed_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "status": True,
                "data": {
                    "reference": "nevo-1",
                    "status": "failed",
                    "amount": 125_000,
                    "currency": "NGN",
                    "gateway_response": "Insufficient funds",
                },
            },
        ),
    )

    result = await PaystackClient(_settings()).verify_transaction("nevo-1")

    assert result.status is PaymentTransactionStatus.FAILED
    assert result.authorization is None
    assert result.gateway_message == "Insufficient funds"


async def test_non_reusable_authorization_is_still_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "status": True,
                "data": {
                    "reference": "nevo-1",
                    "status": "success",
                    "amount": 100,
                    "currency": "NGN",
                    "authorization": {
                        "authorization_code": "AUTH_x",
                        "last4": "0001",
                        "channel": "bank",
                        "reusable": False,
                    },
                },
            },
        ),
    )

    result = await PaystackClient(_settings()).verify_transaction("nevo-1")

    assert result.authorization is not None
    assert result.authorization.reusable is False
    assert result.authorization.method_type is PaymentMethodType.DIRECT_DEBIT


async def test_provider_error_body_is_surfaced(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        lambda request: httpx.Response(
            400, json={"status": False, "message": "Invalid key"}
        ),
    )

    with pytest.raises(PaymentProviderRejectedError, match="Invalid key"):
        await PaystackClient(_settings()).verify_transaction("nevo-1")


async def test_charge_authorization_posts_the_saved_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _install(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "status": True,
                "data": {
                    "reference": "nevo-2",
                    "status": "success",
                    "amount": 5_000,
                    "currency": "NGN",
                },
            },
        ),
    )

    result = await PaystackClient(_settings()).charge_authorization(
        email="bursar@school.test",
        amount=Decimal("50.00"),
        reference="nevo-2",
        authorization_code="AUTH_abc123",
        currency=PricingCurrency.NGN,
    )

    body = json.loads(requests[0].content)
    assert body["authorization_code"] == "AUTH_abc123"
    assert body["amount"] == 5_000
    assert result.status is PaymentTransactionStatus.SUCCESS
