"""/me: a reminder before a paid month lapses - once, and only when it means something."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from tests.integration.test_me_identity import URL, _address, _register

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not URL, reason="Disposable database required"),
]


def _verified(client, mailer):
    email = _address()
    _register(client, email, born=date(2001, 5, 1))
    client.post(
        "/api/v1/auth/verify-email", json={"email": email, "code": mailer.code_for(email)}
    )
    return email


def _month(sessions, email, *, ends_in, starts_ago=27):
    from nevo.db.models.account import User
    from nevo.db.models.me import MePurchase

    async def run():
        async with sessions.begin() as session:
            learner = await session.scalar(select(User).where(User.email == email))
            now = datetime.now(UTC)
            purchase = MePurchase(
                learner_id=learner.id, tier_key="monthly_12", amount_minor=249_900,
                currency="NGN", reference=f"nevo-me-test-{uuid4().hex}", status="success",
                created_at=now, paid_at=now,
                period_start=now - timedelta(days=starts_ago),
                period_end=now + ends_in,
            )
            session.add(purchase)
            await session.flush()
            return purchase.id

    return asyncio.run(run())


def _reminded_at(sessions, purchase_id):
    from nevo.db.models.me import MePurchase

    async def run():
        async with sessions() as session:
            return (await session.get(MePurchase, purchase_id)).reminder_sent_at

    return asyncio.run(run())


def _run(sessions, mailer):
    from nevo.me.reminders import send_renewal_reminders

    return asyncio.run(send_renewal_reminders(sessions, mailer))


def _sent_to(mailer, email):
    from nevo.notifications.me_copy import RENEWAL_SUBJECT

    return [m for m in mailer.sent if m["to"] == email and m["subject"] == RENEWAL_SUBJECT]


@pytest.fixture
def billing_on(monkeypatch):
    from nevo.core.config import get_settings

    monkeypatch.setenv("ME_BILLING_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_a_month_ending_soon_is_reminded_once(me, billing_on):
    client, mailer, sessions = me
    email = _verified(client, mailer)
    purchase = _month(sessions, email, ends_in=timedelta(days=2))

    _run(sessions, mailer)
    _run(sessions, mailer)

    assert len(_sent_to(mailer, email)) == 1
    assert _reminded_at(sessions, purchase) is not None
    assert "ends on" in _sent_to(mailer, email)[0]["text"]
    assert "renews by itself" in _sent_to(mailer, email)[0]["text"]


def test_a_month_with_time_left_is_not_reminded_yet(me, billing_on):
    client, mailer, sessions = me
    email = _verified(client, mailer)
    _month(sessions, email, ends_in=timedelta(days=10))

    _run(sessions, mailer)

    assert _sent_to(mailer, email) == []


def test_a_learner_who_already_renewed_is_not_reminded(me, billing_on):
    client, mailer, sessions = me
    email = _verified(client, mailer)
    ending = _month(sessions, email, ends_in=timedelta(days=2))
    _month(sessions, email, ends_in=timedelta(days=32), starts_ago=-2)  # queued behind it

    _run(sessions, mailer)

    assert _sent_to(mailer, email) == []
    assert _reminded_at(sessions, ending) is None


def test_an_unverified_address_is_never_mailed(me, billing_on):
    client, mailer, sessions = me
    email = _address()
    _register(client, email, born=date(2001, 5, 1))  # never verified
    _month(sessions, email, ends_in=timedelta(days=1))

    _run(sessions, mailer)

    assert _sent_to(mailer, email) == []


def test_a_failed_send_is_tried_again_tomorrow(me, billing_on, monkeypatch):
    client, mailer, sessions = me
    email = _verified(client, mailer)
    purchase = _month(sessions, email, ends_in=timedelta(days=2))
    from nevo.notifications.email import EmailDeliveryUnavailableError

    real_send = type(mailer).send

    async def down(self, **kwargs):
        raise EmailDeliveryUnavailableError("down")

    monkeypatch.setattr(type(mailer), "send", down)
    _run(sessions, mailer)
    assert _reminded_at(sessions, purchase) is None

    monkeypatch.setattr(type(mailer), "send", real_send)
    _run(sessions, mailer)
    assert _reminded_at(sessions, purchase) is not None
    assert len(_sent_to(mailer, email)) == 1


def test_nothing_is_sent_while_billing_is_off(me, monkeypatch):
    client, mailer, sessions = me
    from nevo.core.config import get_settings

    monkeypatch.setenv("ME_BILLING_ENABLED", "false")
    get_settings.cache_clear()
    email = _verified(client, mailer)
    _month(sessions, email, ends_in=timedelta(days=1))

    assert _run(sessions, mailer).startswith("skipped")
    assert _sent_to(mailer, email) == []


def test_the_end_date_is_said_in_lagos_time():
    from nevo.me.reminders import ends_on

    # 23:30 UTC on 30 November is already 1 December in Lagos.
    assert ends_on(datetime(2026, 11, 30, 23, 30, tzinfo=UTC)) == "1 December 2026"
