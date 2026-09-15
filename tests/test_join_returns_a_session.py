"""Finishing onboarding should leave a child signed in.

The two account-creation paths were asymmetric. auth/pin returned a session
and the class-code child was signed in; join/{token}/accept did not, so a
child who arrived by QR or invite link finished onboarding signed out, landed
on fixture content instead of their own lessons, and had whatever they did
during onboarding stranded with no session to submit it under. They also had
no school code, so the sign-in screen could not help them come back.
"""

from __future__ import annotations

from nevo.main import app

JOIN = "/api/v1/join/{token}/accept"
PIN = "/api/v1/auth/pin"


def _response_schema(path: str) -> dict:
    spec = app.openapi()
    operation = spec["paths"][path]["post"]
    success = next(body for code, body in operation["responses"].items() if code.startswith("2"))
    content = success["content"]["application/json"]["schema"]
    name = content["$ref"].rsplit("/", 1)[-1]
    return spec["components"]["schemas"][name]


def test_the_invite_path_hands_back_a_session() -> None:
    assert "session" in _response_schema(JOIN)["properties"]


def test_both_account_creation_paths_agree() -> None:
    # Whichever door a child comes through, they end up in the same state.
    join = _response_schema(JOIN)["properties"]["session"]
    pin = _response_schema(PIN)["properties"]["session"]
    assert join == pin


def test_the_session_is_the_ordinary_one() -> None:
    # Not a new shape to learn: the same SessionResponse every other sign-in
    # returns, so a client stores it the way it already does.
    session = _response_schema(JOIN)["properties"]["session"]
    assert any(
        option.get("$ref", "").endswith("/SessionResponse")
        for option in session.get("anyOf", [session])
    )
