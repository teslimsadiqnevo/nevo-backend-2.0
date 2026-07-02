from fastapi import FastAPI
from fastapi.testclient import TestClient

from nevo.api.auth import router
from tests.auth.test_service import auth_user, harness_for


def client_for(*users):
    harness = harness_for(*users)
    app = FastAPI()
    app.state.auth_service = harness.service
    app.include_router(router)
    return TestClient(app), harness


def test_password_login_and_session_lookup() -> None:
    user = auth_user(
        role="teacher",
        auth_method="email_password",
        email="teacher@example.com",
        password="valid-password",
        pin=None,
        login_identifier=None,
        school_auth_method="email_password",
    )
    client, _ = client_for(user)

    login = client.post(
        "/api/v1/auth/login/password",
        json={
            "email": "teacher@example.com",
            "password": "valid-password",
        },
    )
    assert login.status_code == 200
    payload = login.json()
    assert payload["role"] == "teacher"
    assert payload["token_type"] == "bearer"
    assert login.headers["Cache-Control"] == "no-store"

    session = client.get(
        "/api/v1/auth/session",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )
    assert session.status_code == 200
    assert session.json()["user_id"] == str(user.id)


def test_invalid_credentials_return_stable_generic_error() -> None:
    client, _ = client_for()

    response = client.post(
        "/api/v1/auth/login/password",
        json={
            "email": "unknown@example.com",
            "password": "does-not-exist",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == {
        "code": "authentication_failed",
        "message": "Unable to authenticate with the supplied credentials.",
    }


def test_missing_bearer_token_returns_invalid_session() -> None:
    client, _ = client_for()

    response = client.get("/api/v1/auth/session")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_session"


def test_replaced_student_session_returns_required_message() -> None:
    client, _ = client_for(auth_user())
    request = {
        "school_code": "NVS",
        "login_identifier": "UZ59R",
        "pin": "2443",
    }
    first = client.post("/api/v1/auth/login/pin", json=request).json()
    second = client.post("/api/v1/auth/login/pin", json=request).json()
    assert second["replaced_session"] is True

    response = client.get(
        "/api/v1/auth/session",
        headers={"Authorization": f"Bearer {first['access_token']}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == {
        "code": "session_replaced",
        "message": "You logged in on another device, your progress has been saved.",
    }


def test_pin_payload_is_validated() -> None:
    client, _ = client_for(auth_user())

    response = client.post(
        "/api/v1/auth/login/pin",
        json={
            "school_code": "NVS",
            "login_identifier": "UZ59R",
            "pin": "not-a-pin",
        },
    )

    assert response.status_code == 422


def test_logout_revokes_current_token() -> None:
    client, _ = client_for(auth_user())
    login = client.post(
        "/api/v1/auth/login/pin",
        json={
            "school_code": "NVS",
            "login_identifier": "UZ59R",
            "pin": "2443",
        },
    ).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}

    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/auth/session", headers=headers).status_code == 401


def test_rate_limit_error_maps_to_http_429() -> None:
    client, harness = client_for(auth_user())
    harness.limiter.blocked = True

    response = client.post(
        "/api/v1/auth/login/pin",
        json={
            "school_code": "NVS",
            "login_identifier": "UZ59R",
            "pin": "2443",
        },
    )

    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "too_many_attempts"
