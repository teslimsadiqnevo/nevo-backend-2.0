"""/me Phase 0: the route guard refuses at the boundary, loudly.

The trap it closes: ``school_id = NULL`` matches no rows and succeeds, so a
learner with no school gets an empty page and nothing reports a problem. These
tests hold the rule that such a learner gets an error, never an empty answer.
"""

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nevo.api.account_scope import (
    SHARED_ROUTES,
    RouteAudience,
    audience_for,
)
from nevo.api.auth import router as auth_router
from nevo.api.dependencies import database_session
from nevo.api.product_learning import router as learning_router
from nevo.auth.entities import AuthPrincipal
from nevo.auth.service import AuthService

#: A learner route that stays school-only: a teacher's view of one child.
SCHOOL_ROUTE = f"/api/v1/students/{uuid4()}/profile"


class _FixedPrincipalAuth(AuthService):
    """An AuthService that answers every token with one principal."""

    def __init__(self, principal: AuthPrincipal) -> None:
        self._principal = principal

    async def authenticate(self, access_token: str) -> AuthPrincipal:
        return self._principal


class _NoQueries:
    """Any use of the database fails the test: refusal must come first."""

    def __getattr__(self, name: str):
        raise AssertionError(f"the handler reached the database ({name})")


def _client(principal: AuthPrincipal) -> TestClient:
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(learning_router)
    app.state.auth_service = _FixedPrincipalAuth(principal)
    app.dependency_overrides[database_session] = lambda: _NoQueries()
    return TestClient(app, raise_server_exceptions=False)


def _principal(**overrides) -> AuthPrincipal:
    values = {
        "user_id": uuid4(),
        "role": "student",
        "session_id": uuid4(),
        "account_type": "school",
        "school_id": uuid4(),
    }
    values.update(overrides)
    return AuthPrincipal(**values)


def test_individual_learner_on_a_school_route_is_refused_not_given_an_empty_page():
    client = _client(_principal(account_type="individual", school_id=None))

    response = client.get(SCHOOL_ROUTE, headers={"Authorization": "Bearer t"})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "school_account_required"


def test_school_learner_with_no_school_is_refused_rather_than_matching_nothing():
    client = _client(_principal(school_id=None))

    response = client.get(SCHOOL_ROUTE, headers={"Authorization": "Bearer t"})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "school_scope_missing"


def test_individual_account_can_still_read_its_own_session():
    client = _client(_principal(account_type="individual", school_id=None))

    response = client.get("/api/v1/auth/session", headers={"Authorization": "Bearer t"})

    assert response.status_code == 200


def test_school_account_is_refused_on_an_individual_route():
    from fastapi import Request

    from nevo.api.account_scope import enforce_account_scope

    app = FastAPI()

    @app.get("/api/v1/me/usage")
    async def usage(request: Request):
        enforce_account_scope(request, _principal())
        return {}

    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/me/usage")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "individual_account_required"


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/api/v1/me", RouteAudience.INDIVIDUAL_ONLY),
        ("GET", "/api/v1/me/usage", RouteAudience.INDIVIDUAL_ONLY),
        ("GET", "/api/v1/meetings", RouteAudience.SCHOOL_ONLY),
        ("GET", "/api/v1/students/me/dashboard", RouteAudience.SHARED),
        ("GET", "/api/v1/students/{student_id}/profile", RouteAudience.SCHOOL_ONLY),
        ("GET", "/api/v1/parents/me/children", RouteAudience.SCHOOL_ONLY),
        ("GET", "/api/v1/auth/session", RouteAudience.SHARED),
        ("get", "/api/v1/auth/session", RouteAudience.SHARED),
    ],
)
def test_classification(method, path, expected):
    assert audience_for(method, path) is expected


def test_every_shared_route_exists_in_the_app():
    """A typo in SHARED_ROUTES would silently leave a route school-only."""

    from nevo.main import app

    registered = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }
    assert SHARED_ROUTES <= registered, SHARED_ROUTES - registered
