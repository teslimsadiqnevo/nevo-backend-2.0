"""Lydia's answers of 24 November 2026, held as tests.

C. A paid allowance runs with the month that was bought, not the calendar.
D. An adult's acceptance of the terms at sign-up is recorded.
The approved copy reaches the emails, and every refusal carries what its
message needs.
"""

import asyncio
import re
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from tests.integration.test_me_identity import URL, _address, _register

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not URL, reason="Disposable database required"),
]


def _signed_in(client, mailer, *, born=date(2001, 5, 1)):
    email = _address()
    _register(client, email, born=born)
    token = client.post(
        "/api/v1/auth/verify-email", json={"email": email, "code": mailer.code_for(email)}
    ).json()["accessToken"]
    return email, {"Authorization": f"Bearer {token}"}


def _learner_id(sessions, email):
    from nevo.db.models.account import User

    async def run():
        async with sessions() as session:
            return await session.scalar(select(User.id).where(User.email == email))

    return asyncio.run(run())


def _bought(sessions, learner_id, *, tier="monthly_12", started_days_ago=5):
    from nevo.db.models.me import MePurchase

    async def run():
        async with sessions.begin() as session:
            now = datetime.now(UTC)
            start = now - timedelta(days=started_days_ago)
            session.add(
                MePurchase(
                    learner_id=learner_id, tier_key=tier, amount_minor=1, currency="NGN",
                    reference=f"nevo-me-test-{uuid4().hex}", status="success",
                    created_at=start, paid_at=start, period_start=start,
                    period_end=start + timedelta(days=30),
                )
            )
            return start + timedelta(days=30)

    return asyncio.run(run())


def _upload(client, auth):
    return client.post(
        "/api/v1/uploads",
        headers=auth,
        files={"file": ("notes.txt", f"Osmosis notes {uuid4()}".encode(), "text/plain")},
    )


def _backdate_uploads(sessions, learner_id, days):
    from nevo.db.models.product import UploadJob

    async def run():
        async with sessions.begin() as session:
            await session.execute(
                update(UploadJob)
                .where(UploadJob.requested_by_id == learner_id)
                .values(created_at=datetime.now(UTC) - timedelta(days=days))
            )

    asyncio.run(run())


# -- C ---------------------------------------------------------------------


def test_a_paid_allowance_resets_on_the_purchase_anniversary(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer)
    learner_id = _learner_id(sessions, email)
    ends = _bought(sessions, learner_id, started_days_ago=5)

    usage = client.get("/api/v1/me/usage", headers=auth).json()

    assert usage["allowance"] == 12
    assert abs(datetime.fromisoformat(usage["resetsAt"]) - ends) < timedelta(seconds=1)


def test_uploads_before_the_bought_month_do_not_count_against_it(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer)
    learner_id = _learner_id(sessions, email)
    _upload(client, auth)
    _upload(client, auth)
    _backdate_uploads(sessions, learner_id, days=6)  # free-tier uploads, before buying
    _bought(sessions, learner_id, started_days_ago=5)

    assert client.get("/api/v1/me/usage", headers=auth).json()["used"] == 0


def test_the_free_tier_still_resets_on_the_calendar_month(me):
    client, mailer, _ = me
    _, auth = _signed_in(client, mailer)

    resets = datetime.fromisoformat(client.get("/api/v1/me/usage", headers=auth).json()["resetsAt"])

    # Midnight on the 1st in Lagos is 23:00 UTC the day before.
    assert (resets.hour, resets.minute) == (23, 0)


# -- Refusal details ---------------------------------------------------------


def test_the_allowance_refusal_names_the_next_tier(me):
    client, mailer, _ = me
    _, auth = _signed_in(client, mailer)
    for _ in range(3):
        _upload(client, auth)

    detail = _upload(client, auth).json()["detail"]

    assert detail["code"] == "upload_allowance_exhausted"
    assert detail["upgradeTo"] == {"tier": "monthly_12", "lessonsPerMonth": 12, "priceNaira": 2499}
    assert "resetsAt" in detail["usage"]


def test_the_top_tier_refusal_offers_contact_not_a_price(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer)
    _bought(sessions, _learner_id(sessions, email), tier="monthly_25")

    for _ in range(25):
        if _upload(client, auth).status_code != 201:
            break
    detail = _upload(client, auth).json()["detail"]

    assert detail["offer"] == "contact"
    assert "upgradeTo" not in detail


def test_the_consent_refusal_says_where_the_request_went(me):
    client, mailer, _ = me
    today = datetime.now(UTC).date()
    _, auth = _signed_in(client, mailer, born=date(today.year - 16, 1, 1))
    guardian = _address()
    client.post("/api/v1/me/guardian-invite", headers=auth, json={"contact": guardian})

    detail = _upload(client, auth).json()["detail"]

    assert detail["code"] == "upload_consent_required"
    assert detail["guardianContact"] == guardian


# -- D ---------------------------------------------------------------------


def test_sign_up_requires_and_records_the_terms(me):
    client, _, sessions = me
    refused = client.post(
        "/api/v1/auth/register",
        json={
            "firstName": "Ada", "email": _address(), "password": "correct horse battery",
            "dateOfBirth": "2001-05-01",
        },
    )
    assert refused.status_code == 422

    email = _address()
    _register(client, email)

    from nevo.db.models.account import User

    async def stored():
        async with sessions() as session:
            user = await session.scalar(select(User).where(User.email == email))
            return user.terms_accepted_at, user.terms_version

    accepted_at, version = asyncio.run(stored())
    assert accepted_at is not None
    assert version


# -- Copy ------------------------------------------------------------------


def test_the_emails_use_the_approved_words(me):
    client, mailer, _ = me
    email = _address()
    _register(client, email)
    verify = [m for m in mailer.sent if m["to"] == email][-1]
    assert verify["subject"] == "Your Nevo verification code"
    assert re.search(
        r"It works for the next 30 minutes\. If you did not sign up for Nevo", verify["text"]
    )

    today = datetime.now(UTC).date()
    _, auth = _signed_in(client, mailer, born=date(today.year - 16, 1, 1))
    guardian = _address()
    client.post("/api/v1/me/guardian-invite", headers=auth, json={"contact": guardian})
    invite = [m for m in mailer.sent if m["to"] == guardian][-1]
    assert invite["subject"] == "Ada needs your consent to use Nevo"
    assert "Ada has named you as their parent or guardian." in invite["text"]
    assert "Ada will not be able to upload anything." in invite["text"]


def test_a_failed_preparation_reads_as_lydia_wrote_it(me):
    client, mailer, sessions = me
    _, auth = _signed_in(client, mailer)
    upload_id = _upload(client, auth).json()["uploadId"]

    from nevo.db.models.product import UploadJob

    async def fail():
        async with sessions.begin() as session:
            await session.execute(
                update(UploadJob)
                .where(UploadJob.id == upload_id)
                .values(status="failed", failure_reason="A teacher-facing reason.")
            )

    asyncio.run(fail())
    status = client.get(f"/api/v1/uploads/{upload_id}", headers=auth).json()

    assert status["failureReason"] == (
        "Nevo could not prepare this one. Try uploading it again, and if it still does "
        "not work, send it to us and we will look at it."
    )
