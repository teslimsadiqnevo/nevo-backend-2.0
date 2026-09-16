"""The one route out of the console when something has gone wrong.

Design ruled Help and support carries three facts: an email, a WhatsApp number
and how long an answer takes. None lived in the backend, so the shipped console
offered a menu item that closed the menu and did nothing.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from nevo.api.support import SupportSettings, support_settings, whatsapp_link
from nevo.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_it_answers_without_a_session(client: TestClient) -> None:
    # A teacher who cannot sign in is exactly the person who needs this, so
    # putting it behind the session they have lost would fail in the one place
    # it must not.
    response = client.get("/api/v1/support-contact")

    assert response.status_code == 200


def test_it_carries_the_real_whatsapp_number(client: TestClient) -> None:
    body = client.get("/api/v1/support-contact").json()

    assert body["whatsapp"]["number"] == "+234 906 467 8114"
    assert body["email"] == "support@nevolearning.com"


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        ("+234 906 467 8114", "https://wa.me/2349064678114"),
        ("+2349064678114", "https://wa.me/2349064678114"),
        ("0906 467 8114", "https://wa.me/09064678114"),
    ],
)
def test_the_link_is_digits_only(number: str, expected: str) -> None:
    # wa.me fails silently on a plus or a space, which reads to a teacher as a
    # dead link rather than a malformed one.
    assert whatsapp_link(number) == expected


def test_the_response_time_is_absent_until_somebody_commits_to_one(
    client: TestClient,
) -> None:
    """The two response times in the product are a landing-page sales promise
    and a 48-hour NDPA data-rights obligation. Neither is a support
    commitment, and publishing one as though it were would make a promise to
    schools that nobody has made."""
    body = client.get("/api/v1/support-contact").json()

    assert body["responseTime"] is None


def test_it_can_be_set_without_a_release(client: TestClient) -> None:
    # Answering the open question should be configuration, not a deploy.
    app.dependency_overrides[support_settings] = lambda: SupportSettings(
        SUPPORT_RESPONSE_TIME="We reply within one working day"
    )
    try:
        body = client.get("/api/v1/support-contact").json()
        assert body["responseTime"] == "We reply within one working day"
    finally:
        app.dependency_overrides.pop(support_settings, None)
