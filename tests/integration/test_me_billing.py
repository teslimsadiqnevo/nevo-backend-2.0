"""/me Phase 4: a learner buys a month; the verified webhook grants it.

Done when: a learner can buy a month, the webhook grants it, the allowance
rises, and nothing anywhere stores an instrument.
"""

import asyncio
import hashlib
import hmac
import json
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from tests.integration.test_me_identity import URL, _address, _register

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not URL, reason="Disposable database required"),
]

SECRET = "sk_test_" + "x" * 40
WEBHOOK = "/api/billing/payments/webhook"


class FakePaystack:
    """Stands in for Paystack's API: checkout URLs out, verified state back."""

    def __init__(self) -> None:
        self.initialized: list[dict] = []
        self.verdicts: dict[str, tuple[str, int, str]] = {}

    def install(self, app, sessions):
        from nevo.domain.billing.vocabulary import PaymentMethodType
        from nevo.me.billing import IndividualSettler
        from nevo.payments.config import PaystackSettings
        from nevo.payments.entities import ProviderAuthorization, ProviderTransaction
        from nevo.payments.paystack import STATUS_BY_PROVIDER_VALUE, PaystackClient
        from nevo.payments.repositories import SqlAlchemyPaymentRepository
        from nevo.payments.service import PaymentService

        fake = self

        class Client(PaystackClient):
            async def initialize_transaction(self, **kwargs):
                fake.initialized.append(kwargs)
                return f"https://checkout.paystack.test/{kwargs['reference']}"

            async def verify_transaction(self, reference):
                status, amount, currency = fake.verdicts[reference]
                return ProviderTransaction(
                    reference=reference,
                    status=STATUS_BY_PROVIDER_VALUE[status],
                    amount_minor=amount,
                    currency=currency,
                    provider_reference=f"ps-{reference}",
                    paid_at=datetime.now(UTC),
                    customer_email=None,
                    # Paystack returns a reusable authorization; it must be ignored.
                    authorization=ProviderAuthorization(
                        authorization_code="AUTH_should_never_be_kept",
                        method_type=PaymentMethodType.CARD,
                        last_four="4081",
                        card_brand="visa",
                        bank_name="Test Bank",
                        expiry_month=12,
                        expiry_year=2030,
                        account_name=None,
                        reusable=True,
                    ),
                    gateway_message="Approved" if status == "success" else "Declined",
                )

        settings = PaystackSettings(PAYSTACK_SECRET_KEY=SECRET)
        app.state.payment_service = PaymentService(
            repository=SqlAlchemyPaymentRepository(sessions),
            client=Client(settings),
            settings=settings,
            individual_settler=IndividualSettler(sessions),
        )


def _signed_in(client, mailer, *, born=date(2001, 5, 1)):
    email = _address()
    _register(client, email, born=born)
    token = client.post(
        "/api/v1/auth/verify-email", json={"email": email, "code": mailer.code_for(email)}
    ).json()["accessToken"]
    return email, {"Authorization": f"Bearer {token}"}


def _webhook(client, reference, *, event="charge.success", secret=SECRET):
    body = json.dumps(
        {"event": event, "data": {"id": str(uuid4()), "reference": reference}}
    ).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
    return client.post(
        WEBHOOK,
        content=body,
        headers={"x-paystack-signature": signature, "content-type": "application/json"},
    )


@pytest.fixture
def paying(me, monkeypatch):
    client, mailer, sessions = me
    from nevo.core.config import get_settings

    monkeypatch.setenv("ME_BILLING_ENABLED", "true")
    get_settings.cache_clear()
    fake = FakePaystack()
    fake.install(client.app, sessions)
    return client, mailer, sessions, fake


def _buy(client, auth, fake, tier="monthly_12", verdict=("success", 249_900, "NGN")):
    checkout = client.post("/api/v1/me/checkout", headers=auth, json={"tier": tier})
    assert checkout.status_code == 201, checkout.json()
    reference = checkout.json()["reference"]
    fake.verdicts[reference] = verdict
    return reference


def test_a_key_alone_never_opens_checkout(me, monkeypatch):
    client, mailer, sessions = me
    from nevo.core.config import get_settings

    monkeypatch.setenv("ME_BILLING_ENABLED", "false")
    get_settings.cache_clear()
    fake = FakePaystack()
    fake.install(client.app, sessions)  # a live-looking key is set
    _, auth = _signed_in(client, mailer)

    refused = client.post("/api/v1/me/checkout", headers=auth, json={"tier": "monthly_12"})

    assert refused.status_code == 404
    assert fake.initialized == []
    assert client.get("/api/v1/me/tiers", headers=auth).json()["purchasable"] is False


def test_tiers_are_the_configured_prices(paying):
    client, mailer, _, _ = paying
    _, auth = _signed_in(client, mailer)

    body = client.get("/api/v1/me/tiers", headers=auth).json()

    assert [(t["key"], t["lessonsPerMonth"], t.get("priceNaira")) for t in body["tiers"]] == [
        ("free", 3, None),
        ("monthly_12", 12, 2499),
        ("monthly_25", 25, 6999),
    ]
    assert body["purchasable"] is True
    assert body["aboveTopTier"] == "contact"


def test_checkout_is_pending_until_the_webhook_grants_the_month(paying):
    client, mailer, _, fake = paying
    _, auth = _signed_in(client, mailer)

    reference = _buy(client, auth, fake)
    sent = fake.initialized[-1]
    assert sent["amount"] == 2499 and sent["channels"] == ["card", "bank", "ussd", "bank_transfer"]
    # Paid at Paystack, returned to the app - and still nothing until the webhook.
    assert client.get("/api/v1/me/subscription", headers=auth).json() == {
        "tier": "free",
        "autoRenews": False,
    }
    assert client.get("/api/v1/me/usage", headers=auth).json()["allowance"] == 3

    granted = _webhook(client, reference)

    assert granted.status_code == 200
    assert granted.json()["applied"] is True
    subscription = client.get("/api/v1/me/subscription", headers=auth).json()
    assert subscription["tier"] == "monthly_12"
    assert "periodEnd" in subscription
    assert client.get("/api/v1/me/usage", headers=auth).json()["allowance"] == 12


def test_a_replayed_webhook_is_applied_once(paying):
    client, mailer, _, fake = paying
    _, auth = _signed_in(client, mailer)
    reference = _buy(client, auth, fake)
    event = {"event": "charge.success", "data": {"id": str(uuid4()), "reference": reference}}
    body = json.dumps(event)
    signature = hmac.new(SECRET.encode(), body.encode(), hashlib.sha512).hexdigest()
    headers = {"x-paystack-signature": signature, "content-type": "application/json"}

    first = client.post(WEBHOOK, content=body, headers=headers)
    second = client.post(WEBHOOK, content=body, headers=headers)

    assert first.json()["applied"] is True
    assert second.json()["applied"] is False


def test_the_wrong_amount_grants_nothing(paying):
    client, mailer, _, fake = paying
    _, auth = _signed_in(client, mailer)
    reference = _buy(client, auth, fake, verdict=("success", 100, "NGN"))

    _webhook(client, reference)

    assert client.get("/api/v1/me/subscription", headers=auth).json()["tier"] == "free"


def test_an_unsigned_webhook_grants_nothing(paying):
    client, mailer, _, fake = paying
    _, auth = _signed_in(client, mailer)
    reference = _buy(client, auth, fake)

    forged = _webhook(client, reference, secret="not-the-secret-" + "y" * 30)

    assert forged.status_code == 401
    assert client.get("/api/v1/me/subscription", headers=auth).json()["tier"] == "free"


def test_renewing_early_queues_the_next_month_behind_this_one(paying):
    client, mailer, _, fake = paying
    _, auth = _signed_in(client, mailer)
    _webhook(client, _buy(client, auth, fake))
    first_end = datetime.fromisoformat(
        client.get("/api/v1/me/subscription", headers=auth).json()["periodEnd"]
    )

    _webhook(client, _buy(client, auth, fake))

    second_end = datetime.fromisoformat(
        client.get("/api/v1/me/subscription", headers=auth).json()["periodEnd"]
    )
    assert second_end > first_end
    assert (second_end - first_end).days in {28, 29, 30, 31}


def test_the_top_tier_lifts_the_allowance_to_twenty_five(paying):
    client, mailer, _, fake = paying
    _, auth = _signed_in(client, mailer)

    _webhook(client, _buy(client, auth, fake, "monthly_25", ("success", 699_900, "NGN")))

    assert client.get("/api/v1/me/usage", headers=auth).json()["allowance"] == 25


def test_an_under_18_without_consent_cannot_buy(paying):
    client, mailer, _, fake = paying
    today = datetime.now(UTC).date()
    _, auth = _signed_in(client, mailer, born=date(today.year - 16, 1, 1))

    refused = client.post("/api/v1/me/checkout", headers=auth, json={"tier": "monthly_12"})

    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "upload_consent_required"
    assert fake.initialized == []


def test_nothing_from_the_authorization_is_kept(paying):
    client, mailer, sessions, fake = paying
    _, auth = _signed_in(client, mailer)
    reference = _buy(client, auth, fake)
    _webhook(client, reference)

    from nevo.db.models.me import MePurchase

    async def row():
        async with sessions() as session:
            return await session.scalar(select(MePurchase).where(MePurchase.reference == reference))

    purchase = asyncio.run(row())
    columns = MePurchase.__table__.columns
    stored = " ".join(str(getattr(purchase, column.name)) for column in columns)
    assert "AUTH_should_never_be_kept" not in stored
    assert "4081" not in stored
