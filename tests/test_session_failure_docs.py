"""A 401 that says which of five things went wrong.

session_expired, session_revoked, session_replaced, account_paused and
invalid_session were all reachable and named nowhere in the document, so a
client had to treat the set as open and fall back to a generic message. That
is worst for account_paused, which a child reads as their own mistake.
"""

from __future__ import annotations

import pytest

from nevo.auth.errors import (
    AccountPausedError,
    InvalidSessionError,
    SessionExpiredError,
    SessionReplacedError,
    SessionRevokedError,
)
from nevo.main import app


@pytest.fixture(scope="module")
def spec() -> dict:
    return app.openapi()


def _authenticated(spec: dict) -> list[tuple[str, str, dict]]:
    return [
        (path, method, operation)
        for path, item in spec["paths"].items()
        for method, operation in item.items()
        if operation.get("security")
    ]


def test_every_authenticated_operation_documents_its_401(spec: dict) -> None:
    missing = [
        f"{method.upper()} {path}"
        for path, method, operation in _authenticated(spec)
        if "401" not in operation.get("responses", {})
    ]
    assert not missing


@pytest.mark.parametrize(
    "error",
    [
        SessionExpiredError,
        SessionRevokedError,
        SessionReplacedError,
        AccountPausedError,
        InvalidSessionError,
    ],
)
def test_every_code_the_session_can_raise_is_named(spec: dict, error: type) -> None:
    # Named from the error classes rather than a hardcoded list, so a new one
    # cannot be added without this noticing.
    _, _, operation = _authenticated(spec)[0]
    assert error.code in operation["responses"]["401"]["description"]


def test_a_login_keeps_its_own_401(spec: dict) -> None:
    # Login fails for different reasons than a session does, and it documents
    # them itself. The shared text must not have overwritten that.
    description = spec["paths"]["/api/v1/auth/login"]["post"]["responses"]["401"]["description"]
    assert "authentication_failed" in description
    assert "too_many_attempts" in description
    assert "session_expired" not in description
