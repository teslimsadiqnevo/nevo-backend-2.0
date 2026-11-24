"""/me Phase 1b: an under-18 nominates a guardian, who consents with no account.

Done when: an under-18 can register, invite a guardian, have upload blocked
by consent (not allowance), and have it open the moment consent lands - and
an unanswered invite goes dormant at fourteen days without losing any action.
"""

import asyncio
import re
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from nevo.db.models.account import ConsentRecord, User
from nevo.db.models.consent import GuardianInvitation
from nevo.domain.accounts.vocabulary import ConsentMethod, ConsentStatus, ConsentType
from nevo.domain.consent.vocabulary import ConsentConfirmationSource
from tests.integration.test_me_identity import URL, _address, _register

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not URL, reason="Disposable database required"),
]


def _sixteen() -> date:
    today = datetime.now(UTC).date()
    return date(today.year - 16, 1, 1)


def _signed_in(client, mailer, *, born):
    email = _address()
    _register(client, email, born=born)
    token = client.post(
        "/api/v1/auth/verify-email", json={"email": email, "code": mailer.code_for(email)}
    ).json()["accessToken"]
    return email, {"Authorization": f"Bearer {token}"}


def _guardian_token(mailer, guardian_email):
    text = [item["text"] for item in mailer.sent if item["to"] == guardian_email][-1]
    return re.search(r"/guardian/([\w-]+)", text).group(1)


def _consent(client, token, **overrides):
    body = {
        "guardianName": "Funmi Adeyemi",
        "guardianContact": "funmi@nevolearning-tests.com",
        "relationship": "mother",
        "dataProcessing": True,
        "crossBorderTransfer": True,
    }
    body.update(overrides)
    return client.post(f"/api/v1/guardian/{token}/consent", json=body)


def _age_invitations(sessions, email, days):
    async def run():
        async with sessions.begin() as session:
            student = await session.scalar(select(User.id).where(User.email == email))
            past = datetime.now(UTC) - timedelta(days=days)
            await session.execute(
                update(GuardianInvitation)
                .where(GuardianInvitation.student_id == student)
                .values(created_at=past, last_sent_at=past)
            )

    asyncio.run(run())


def test_the_whole_route_outstanding_to_granted(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer, born=_sixteen())

    before = client.get("/api/v1/me/consent", headers=auth).json()
    assert before["state"] == "outstanding"
    assert before["blocked"] == ["upload"]
    assert before["actions"] == ["invite_guardian"]

    guardian = _address()
    invited = client.post("/api/v1/me/guardian-invite", headers=auth, json={"contact": guardian})
    assert invited.status_code == 201
    assert invited.json()["guardianContact"] == guardian
    assert invited.json()["actions"] == ["resend_invite", "change_contact"]

    token = _guardian_token(mailer, guardian)
    view = client.get(f"/api/v1/guardian/{token}").json()
    assert view["state"] == "awaiting"
    assert view["learnerFirstName"] == "Ada"
    assert view["consentTypes"] == ["data_processing", "cross_border_transfer"]

    assert _consent(client, token).json() == {"status": "consented"}
    assert _consent(client, token).json() == {"status": "already_consented"}

    after = client.get("/api/v1/me/consent", headers=auth).json()
    assert after["state"] == "granted"
    assert after["blocked"] == []
    who = client.get("/api/v1/auth/me", headers=auth).json()
    assert who["consent"] == {"required": True, "state": "granted"}

    async def records():
        async with sessions() as session:
            student = await session.scalar(select(User.id).where(User.email == email))
            return (
                await session.scalars(
                    select(ConsentRecord).where(ConsentRecord.subject_user_id == student)
                )
            ).all()

    rows = asyncio.run(records())
    assert {row.consent_type for row in rows} == {
        ConsentType.DATA_PROCESSING,
        ConsentType.CROSS_BORDER_TRANSFER,
    }
    for row in rows:
        assert row.status is ConsentStatus.CONFIRMED
        assert row.confirmation_source is ConsentConfirmationSource.GUARDIAN
        assert row.confirmed_by_parent_id is None  # no account was made
        assert row.parent_name_on_form == "Funmi Adeyemi"
        assert row.confirmed_via is ConsentMethod.DIGITAL


def test_upload_blocked_by_consent_until_it_lands(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer, born=_sixteen())
    guardian = _address()
    client.post("/api/v1/me/guardian-invite", headers=auth, json={"contact": guardian})

    from nevo.consent.guardian import upload_blocked_by_consent

    async def blocked():
        async with sessions() as session:
            user = await session.scalar(select(User).where(User.email == email))
            return await upload_blocked_by_consent(session, user)

    assert asyncio.run(blocked()) is True
    _consent(client, _guardian_token(mailer, guardian))
    assert asyncio.run(blocked()) is False


def test_changing_the_contact_retires_the_old_link(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer, born=_sixteen())
    wrong = _address()
    client.post("/api/v1/me/guardian-invite", headers=auth, json={"contact": wrong})
    old = _guardian_token(mailer, wrong)
    _age_invitations(sessions, email, days=0.01)  # past the two-minute send interval

    right = _address()
    changed = client.post("/api/v1/me/guardian-invite", headers=auth, json={"contact": right})

    assert changed.status_code == 201
    assert changed.json()["guardianContact"] == right
    assert client.get(f"/api/v1/guardian/{old}").json()["state"] == "replaced"
    assert _consent(client, old).status_code == 410
    assert _consent(client, _guardian_token(mailer, right)).status_code == 200


def test_resend_is_limited_and_issues_a_fresh_link(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer, born=_sixteen())
    guardian = _address()
    client.post("/api/v1/me/guardian-invite", headers=auth, json={"contact": guardian})
    first = _guardian_token(mailer, guardian)

    too_soon = client.post("/api/v1/me/guardian-invite/resend", headers=auth)
    assert too_soon.status_code == 429
    assert "retryAt" in too_soon.json()["detail"]

    _age_invitations(sessions, email, days=0.01)
    again = client.post("/api/v1/me/guardian-invite/resend", headers=auth)
    assert again.status_code == 200
    second = _guardian_token(mailer, guardian)
    assert second != first
    assert client.get(f"/api/v1/guardian/{first}").status_code == 404
    assert client.get(f"/api/v1/guardian/{second}").json()["state"] == "awaiting"


def test_fourteen_days_unanswered_is_dormant_and_loses_no_action(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer, born=_sixteen())
    guardian = _address()
    client.post("/api/v1/me/guardian-invite", headers=auth, json={"contact": guardian})
    _age_invitations(sessions, email, days=15)

    dormant = client.get("/api/v1/me/consent", headers=auth).json()
    assert dormant["state"] == "dormant"
    assert dormant["actions"] == ["resend_invite", "change_contact"]
    assert "dormantSince" in dormant

    resent = client.post("/api/v1/me/guardian-invite/resend", headers=auth)
    assert resent.status_code == 200
    _consent(client, _guardian_token(mailer, guardian))
    assert client.get("/api/v1/me/consent", headers=auth).json()["state"] == "granted"


def test_thirteen_days_is_still_outstanding(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer, born=_sixteen())
    client.post("/api/v1/me/guardian-invite", headers=auth, json={"contact": _address()})
    _age_invitations(sessions, email, days=13)

    assert client.get("/api/v1/me/consent", headers=auth).json()["state"] == "outstanding"


def test_an_adult_needs_no_guardian(me):
    client, mailer, _ = me
    _, auth = _signed_in(client, mailer, born=date(2000, 1, 1))

    assert client.get("/api/v1/me/consent", headers=auth).json() == {
        "required": False,
        "state": "not_required",
        "blocked": [],
        "actions": [],
    }
    refused = client.post("/api/v1/me/guardian-invite", headers=auth, json={"contact": _address()})
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "consent_not_required"


def test_a_learner_cannot_name_themselves(me):
    client, mailer, _ = me
    email, auth = _signed_in(client, mailer, born=_sixteen())

    refused = client.post("/api/v1/me/guardian-invite", headers=auth, json={"contact": email})

    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "guardian_contact_is_learner"


def test_both_ticks_are_required_and_an_unknown_link_is_404(me):
    client, mailer, _ = me
    _, auth = _signed_in(client, mailer, born=_sixteen())
    guardian = _address()
    client.post("/api/v1/me/guardian-invite", headers=auth, json={"contact": guardian})
    token = _guardian_token(mailer, guardian)

    assert _consent(client, token, crossBorderTransfer=False).status_code == 422
    assert client.get("/api/v1/guardian/not-a-real-link-token").status_code == 404
    assert _consent(client, "not-a-real-link-token").status_code == 404


def test_a_guardian_confirmation_must_name_the_guardian(me):
    _, _, sessions = me

    async def nameless():
        async with sessions.begin() as session:
            student = User(
                account_type="individual",
                role="student",
                auth_method="email_password",
                status="active",
                email=_address(),
            )
            session.add(student)
            await session.flush()
            session.add(
                ConsentRecord(
                    subject_user_id=student.id,
                    consent_type=ConsentType.DATA_PROCESSING,
                    status=ConsentStatus.CONFIRMED,
                    confirmation_source=ConsentConfirmationSource.GUARDIAN,
                    confirmed_via=ConsentMethod.DIGITAL,
                    confirmed_at=datetime.now(UTC),
                )
            )

    with pytest.raises(IntegrityError):
        asyncio.run(nameless())
