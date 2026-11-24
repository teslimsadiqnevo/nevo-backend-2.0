"""/me Phase 3: a learner uploads their own material, gated once.

Done when: a learner can upload, the count goes up, the fourth upload on the
free tier is refused with its own code, and GET /me/usage shows the allowance
and the reset date.
"""

import asyncio
import re
from datetime import UTC, date, datetime
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


def _upload(client, auth, text=None):
    body = text or f"Osmosis is the movement of water across a membrane. {uuid4()}"
    return client.post(
        "/api/v1/uploads",
        headers=auth,
        files={"file": ("notes.txt", body.encode(), "text/plain")},
    )


def test_three_free_lessons_then_a_refusal_with_its_own_code(me):
    client, mailer, _ = me
    _, auth = _signed_in(client, mailer)

    assert client.get("/api/v1/me/usage", headers=auth).json()["remaining"] == 3
    for expected_used in (1, 2, 3):
        assert _upload(client, auth).status_code == 201
        assert client.get("/api/v1/me/usage", headers=auth).json()["used"] == expected_used

    refused = _upload(client, auth)

    assert refused.status_code == 403
    detail = refused.json()["detail"]
    assert detail["code"] == "upload_allowance_exhausted"
    assert detail["offer"] == "upgrade"
    assert detail["usage"]["used"] == 3
    assert detail["usage"]["allowance"] == 3


def test_usage_names_the_tier_and_the_reset(me):
    client, mailer, _ = me
    _, auth = _signed_in(client, mailer)

    body = client.get("/api/v1/me/usage", headers=auth).json()

    assert body["tier"] == "free"
    assert body["allowance"] == 3
    resets = datetime.fromisoformat(body["resetsAt"])
    # Midnight on the 1st, Lagos time (UTC+1): 23:00 UTC on the last day.
    assert (resets.hour, resets.minute) == (23, 0)


def test_the_same_file_again_is_not_a_second_lesson(me):
    client, mailer, _ = me
    _, auth = _signed_in(client, mailer)
    text = f"Diffusion moves particles from high to low concentration. {uuid4()}"

    first = _upload(client, auth, text)
    again = _upload(client, auth, text)

    assert first.status_code == 201
    assert again.json()["uploadId"] == first.json()["uploadId"]
    assert client.get("/api/v1/me/usage", headers=auth).json()["used"] == 1


def test_a_failed_preparation_is_not_charged(me):
    client, mailer, sessions = me
    _, auth = _signed_in(client, mailer)
    upload_id = _upload(client, auth).json()["uploadId"]

    from nevo.db.models.product import UploadJob

    async def fail():
        async with sessions.begin() as session:
            await session.execute(
                update(UploadJob).where(UploadJob.id == upload_id).values(status="failed")
            )

    asyncio.run(fail())
    assert client.get("/api/v1/me/usage", headers=auth).json()["used"] == 0


def test_an_under_18_is_refused_with_the_consent_code_until_consent_lands(me):
    client, mailer, _ = me
    today = datetime.now(UTC).date()
    _, auth = _signed_in(client, mailer, born=date(today.year - 16, 1, 1))

    refused = _upload(client, auth)
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "upload_consent_required"
    assert refused.json()["detail"]["offer"] == "guardian_consent"
    assert client.get("/api/v1/me/usage", headers=auth).json()["used"] == 0

    guardian = _address()
    client.post("/api/v1/me/guardian-invite", headers=auth, json={"contact": guardian})
    text = [item["text"] for item in mailer.sent if item["to"] == guardian][-1]
    token = re.search(r"/guardian/([\w-]+)", text).group(1)
    client.post(
        f"/api/v1/guardian/{token}/consent",
        json={
            "guardianName": "Funmi Adeyemi",
            "guardianContact": guardian,
            "dataProcessing": True,
            "crossBorderTransfer": True,
        },
    )

    assert _upload(client, auth).status_code == 201


def test_a_learner_sees_only_their_own_uploads(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer)
    _, other = _signed_in(client, mailer)
    mine = _upload(client, auth).json()["uploadId"]
    theirs = _upload(client, other).json()["uploadId"]

    listed = {item["id"] for item in client.get("/api/v1/uploads", headers=auth).json()}

    assert listed == {mine}
    assert client.get(f"/api/v1/uploads/{mine}", headers=auth).status_code == 200
    assert client.get(f"/api/v1/uploads/{theirs}", headers=auth).status_code == 404
    assert client.post(f"/api/v1/uploads/{theirs}/confirm", headers=auth).status_code == 404
    # Their own reaches the handler: nothing is parsed yet, so it says so.
    assert client.post(f"/api/v1/uploads/{mine}/confirm", headers=auth).status_code == 409

    from nevo.db.models.account import User
    from nevo.db.models.product import UploadJob

    async def stored():
        async with sessions() as session:
            job = await session.get(UploadJob, mine)
            owner = await session.scalar(select(User.id).where(User.email == email))
            return job.school_id, job.requested_by_id == owner

    assert asyncio.run(stored()) == (None, True)


def test_the_month_turns_over_in_lagos_time():
    from nevo.me.usage import month_window

    start, end = month_window(datetime(2026, 12, 31, 23, 30, tzinfo=UTC))  # Jan 1, 00:30 Lagos
    assert start == datetime(2026, 12, 31, 23, 0, tzinfo=UTC)
    assert end == datetime(2027, 1, 31, 23, 0, tzinfo=UTC)

    start, end = month_window(datetime(2026, 12, 15, tzinfo=UTC))
    assert start == datetime(2026, 11, 30, 23, 0, tzinfo=UTC)
    assert end == datetime(2026, 12, 31, 23, 0, tzinfo=UTC)
