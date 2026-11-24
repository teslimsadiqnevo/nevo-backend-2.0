"""/me Phase 1: an individual registers, verifies, signs in and reads who they are.

Against a real, disposable Postgres at ME_TEST_DATABASE_URL (migrated to
head), because the parts that matter - the unique address, the code digest,
the attempt counting - live in the database.
"""

import asyncio
import os
import re
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

URL = os.getenv("ME_TEST_DATABASE_URL", "")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not URL, reason="Disposable database required"),
]

PASSWORD = "correct horse battery"


class CapturingMailer:
    """Stands in for Resend and keeps what it was asked to send."""

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send(self, *, to, subject, text, html=None, attachment=None) -> None:
        self.sent.append({"to": to, "subject": subject, "text": text})

    def code_for(self, email: str) -> str:
        texts = [item["text"] for item in self.sent if item["to"] == email]
        return re.search(r"\b(\d{6})\b", texts[-1]).group(1)


@pytest.fixture
def me(monkeypatch):
    parsed = make_url(URL)
    assert parsed.host in {"127.0.0.1", "localhost"}
    assert parsed.database == "nevo_me_tests"

    monkeypatch.setenv("AUTH_PASSWORD_PEPPER", "p" * 40)
    monkeypatch.setenv("AUTH_PIN_PEPPER", "i" * 40)
    monkeypatch.setenv("AUTH_SESSION_PEPPER", "s" * 40)
    monkeypatch.setenv("ME_REGISTRATION_ENABLED", "true")

    from nevo.api import product_auth
    from nevo.api.auth import router as auth_router
    from nevo.api.billing import router as billing_router
    from nevo.api.dependencies import database_session
    from nevo.api.frontend_unblockers import router as unblockers_router
    from nevo.api.guardian_consent import router as guardian_router
    from nevo.api.individual_auth import router as individual_router
    from nevo.api.learning_readiness import router as readiness_router
    from nevo.api.mastery import router as mastery_router
    from nevo.api.me_billing import router as me_billing_router
    from nevo.api.me_mastery import router as me_mastery_router
    from nevo.api.me_usage import router as usage_router
    from nevo.api.product_learning import router as learning_router
    from nevo.auth.config import AuthSettings
    from nevo.auth.wiring import build_auth_service
    from nevo.core.config import get_settings
    from nevo.mastery.wiring import build_mastery_service
    from nevo.notifications.email import ResendEmailDelivery

    get_settings.cache_clear()
    product_auth.credential_hasher.cache_clear()

    engine = create_async_engine(URL, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    class Mailer(CapturingMailer, ResendEmailDelivery):
        configured = True
        frontend_base_url = "https://app.nevolearning-tests.com"

        def __init__(self) -> None:
            CapturingMailer.__init__(self)

    mailer = Mailer()
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(individual_router)
    app.include_router(learning_router)
    app.include_router(unblockers_router)
    app.include_router(product_auth.router)
    app.include_router(guardian_router)
    app.include_router(readiness_router)
    app.include_router(usage_router)
    app.include_router(me_billing_router)
    app.include_router(billing_router)
    app.include_router(me_mastery_router)
    app.include_router(mastery_router)
    app.state.mastery_service = build_mastery_service(sessions)
    app.state.auth_service = build_auth_service(sessions, AuthSettings())
    app.state.email_delivery = mailer

    async def session_override():
        async with sessions() as session:
            yield session

    app.dependency_overrides[database_session] = session_override
    client = TestClient(app, raise_server_exceptions=False)
    yield client, mailer, sessions
    get_settings.cache_clear()
    product_auth.credential_hasher.cache_clear()
    asyncio.run(engine.dispose())


def _address() -> str:
    return f"learner-{uuid4().hex[:10]}@nevolearning-tests.com"


def _register(client, email, born=date(2001, 5, 1)):
    return client.post(
        "/api/v1/auth/register",
        json={
            "firstName": "Ada",
            "email": email,
            "password": PASSWORD,
            "dateOfBirth": born.isoformat(),
        },
    )


def _login(client, email):
    return client.post(
        "/api/v1/auth/login/password", json={"email": email, "password": PASSWORD}
    )


def test_register_verify_login_and_read_who_i_am(me):
    client, mailer, _ = me
    email = _address()

    assert _register(client, email).status_code == 202
    refused = _login(client, email)
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "email_unverified"

    wrong = client.post("/api/v1/auth/verify-email", json={"email": email, "code": "000000"})
    if mailer.code_for(email) != "000000":
        assert wrong.status_code == 400
        assert wrong.json()["detail"]["code"] == "verification_code_invalid"

    verified = client.post(
        "/api/v1/auth/verify-email", json={"email": email, "code": mailer.code_for(email)}
    )
    assert verified.status_code == 200
    token = verified.json()["accessToken"]

    who = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert who.status_code == 200
    body = who.json()
    assert body["accountType"] == "individual"
    assert body["emailVerified"] is True
    assert body["consent"] == {"required": False, "state": "not_required"}
    assert "schoolId" not in body  # omitted, not empty

    assert _login(client, email).status_code == 200


def test_an_address_in_use_gets_the_same_answer_and_no_second_account(me):
    client, mailer, sessions = me
    email = _address()
    assert _register(client, email).status_code == 202
    sent = len(mailer.sent)

    again = _register(client, email.upper())

    assert again.status_code == 202
    assert again.json() == {"status": "accepted"}
    assert len(mailer.sent) == sent

    from nevo.db.models.account import User

    async def count():
        async with sessions() as session:
            return await session.scalar(
                select(func.count()).select_from(User).where(func.lower(User.email) == email)
            )

    assert asyncio.run(count()) == 1


def test_an_under_18_is_registered_with_consent_outstanding(me):
    client, mailer, _ = me
    email = _address()
    today = datetime.now(UTC).date()
    born = date(today.year - 16, 1, 1)

    assert _register(client, email, born=born).status_code == 202
    token = client.post(
        "/api/v1/auth/verify-email", json={"email": email, "code": mailer.code_for(email)}
    ).json()["accessToken"]

    body = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["consent"] == {"required": True, "state": "outstanding"}


def test_wrong_codes_pause_verification(me):
    client, mailer, _ = me
    email = _address()
    _register(client, email)
    real = mailer.code_for(email)
    wrong = "111111" if real != "111111" else "222222"

    statuses = [
        client.post("/api/v1/auth/verify-email", json={"email": email, "code": wrong}).status_code
        for _ in range(6)
    ]

    assert statuses[:5] == [400] * 5
    assert statuses[5] == 429
    # Even the right code waits out the pause.
    paused = client.post("/api/v1/auth/verify-email", json={"email": email, "code": real})
    assert paused.status_code == 429


def test_resend_is_held_by_the_mail_limiter_without_saying_so(me):
    client, mailer, _ = me
    email = _address()
    _register(client, email)
    sent = len(mailer.sent)

    held = client.post("/api/v1/auth/verify-email/resend", json={"email": email})
    unknown = client.post("/api/v1/auth/verify-email/resend", json={"email": _address()})

    assert held.status_code == unknown.status_code == 202
    assert len(mailer.sent) == sent


def test_a_verified_individual_cannot_reach_a_school_route(me):
    client, mailer, _ = me
    email = _address()
    _register(client, email)
    token = client.post(
        "/api/v1/auth/verify-email", json={"email": email, "code": mailer.code_for(email)}
    ).json()["accessToken"]

    response = client.get(
        f"/api/v1/students/{uuid4()}/profile", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "school_account_required"


def test_registration_is_absent_while_the_flag_is_off(me, monkeypatch):
    client, _, _ = me
    from nevo.core.config import get_settings

    monkeypatch.setenv("ME_REGISTRATION_ENABLED", "false")
    get_settings.cache_clear()

    assert _register(client, _address()).status_code == 404


def test_a_school_cannot_invite_an_address_held_by_an_individual(me):
    client, _, sessions = me
    email = _address()
    _register(client, email)

    from nevo.api.product_auth import InvitationRequest, _create_invitation

    async def invite():
        async with sessions() as session:
            await _create_invitation(
                InvitationRequest(email=email), object(), session, None
            )

    with pytest.raises(HTTPException) as refused:
        asyncio.run(invite())
    assert refused.value.status_code == 409
    assert refused.value.detail["code"] == "email_held_by_individual_account"


def test_password_reset_reaches_an_individual_account(me):
    client, mailer, _ = me
    email = _address()
    _register(client, email)
    client.post("/api/v1/auth/verify-email", json={"email": email, "code": mailer.code_for(email)})

    requested = client.post("/api/v1/auth/password-reset/request", json={"email": email})
    assert requested.status_code == 200
    link = mailer.sent[-1]["text"]
    token = re.search(r"token=([\w-]+)", link).group(1)

    done = client.post(
        "/api/v1/auth/password-reset/complete",
        json={"token": token, "password": "a brand new passphrase"},
    )
    assert done.status_code == 200
    signed_in = client.post(
        "/api/v1/auth/login/password",
        json={"email": email, "password": "a brand new passphrase"},
    )
    assert signed_in.status_code == 200
