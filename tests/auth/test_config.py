import pytest
from pydantic import ValidationError

from nevo.auth.config import AuthSettings


def settings(**overrides: str) -> AuthSettings:
    values = {
        "auth_password_pepper": "password-pepper-that-is-longer-than-32-chars",
        "auth_pin_pepper": "pin-pepper-that-is-different-and-over-32-chars",
        "auth_session_pepper": "session-pepper-that-is-also-unique-and-long",
    }
    values.update(overrides)
    return AuthSettings(**values)  # type: ignore[arg-type]


def test_accepts_three_distinct_long_peppers() -> None:
    configured = settings()

    assert configured.auth_password_pepper.get_secret_value().startswith("password")


def test_rejects_short_pepper() -> None:
    with pytest.raises(ValidationError, match="at least 32"):
        settings(auth_pin_pepper="too-short")


def test_rejects_reused_pepper() -> None:
    shared = "shared-pepper-that-is-longer-than-thirty-two"

    with pytest.raises(ValidationError, match="must be distinct"):
        settings(
            auth_password_pepper=shared,
            auth_session_pepper=shared,
        )
