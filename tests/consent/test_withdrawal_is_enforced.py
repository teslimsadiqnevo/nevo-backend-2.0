"""Withdrawal has to do something.

A parent completing a withdrawal is told it suspends their child's access
immediately. The gate that answers "is this learner blocked" was built, and
then attached to nothing: `require_student_consent` had one caller, the
endpoint that reports the gate, so the promise made to parents was not kept
anywhere in the product.

These tests hold the gate onto the endpoints that do the processing.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from nevo.api import consent as consent_api
from nevo.api.consent import require_learning_consent_if_student
from nevo.auth.entities import AuthPrincipal
from nevo.consent.entities import ConsentGate
from nevo.consent.errors import ConsentWithdrawnError
from nevo.consent.service import REQUIRED_LEARNING_CONSENT
from nevo.domain.accounts.vocabulary import ConsentStatus

GATED = (
    ("post", "/api/v1/lessons/{lesson_id}/session"),
    ("put", "/api/v1/lessons/{lesson_id}/progress"),
    ("post", "/api/v1/lessons/{lesson_id}/download"),
    ("post", "/api/v1/ask-nevo/"),
)


class _Service:
    """Stands in for the consent service, recording who it was asked about."""

    def __init__(self, *, withdrawn: bool) -> None:
        self.withdrawn = withdrawn
        self.asked_about: list[AuthPrincipal] = []

    async def require_student_consent(self, principal: AuthPrincipal) -> ConsentGate:
        self.asked_about.append(principal)
        if self.withdrawn:
            raise ConsentWithdrawnError
        return ConsentGate(
            student_id=principal.user_id,
            granted=True,
            blocked=False,
            required_type=REQUIRED_LEARNING_CONSENT,
            status=ConsentStatus.CONFIRMED,
        )


def _principal(role: str) -> AuthPrincipal:
    return AuthPrincipal(user_id=uuid4(), role=role, session_id=uuid4())


def _request(service: _Service | None) -> SimpleNamespace:
    """Just enough of a Request for the dependency to find the service."""

    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(consent_service=service)))


@pytest.mark.asyncio
async def test_a_withdrawn_learner_is_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _Service(withdrawn=True)
    monkeypatch.setattr(consent_api, "get_consent_service", lambda request: service)

    with pytest.raises(HTTPException) as raised:
        await require_learning_consent_if_student(_request(service), _principal("student"))

    assert raised.value.status_code == 403


@pytest.mark.asyncio
async def test_a_learner_with_consent_carries_on(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _Service(withdrawn=False)
    monkeypatch.setattr(consent_api, "get_consent_service", lambda request: service)

    gate = await require_learning_consent_if_student(_request(service), _principal("student"))

    assert gate is not None
    assert gate.blocked is False


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["teacher", "senco_admin", "other_admin", "parent_guardian"])
async def test_nobody_elses_access_depends_on_a_pupils_consent(role: str) -> None:
    # These endpoints are shared. A teacher opening a lesson has their own
    # authorisation and no consent record of their own to check - and their
    # access must not fail when the consent service is down, so the service
    # is never even looked up for them.
    assert await require_learning_consent_if_student(_request(None), _principal(role)) is None


@pytest.mark.parametrize(("method", "path"), GATED)
def test_the_gate_is_attached_to_every_processing_endpoint(method: str, path: str) -> None:
    # The fault was never the gate's logic - it was that nothing called it.
    route = _route(method, path)
    assert route is not None, f"{method.upper()} {path} is not routed"
    assert "require_learning_consent_if_student" in _dependency_names(route)


def _route(method: str, path: str) -> object | None:
    import importlib
    import pkgutil

    import nevo.api as api_package

    for module in pkgutil.iter_modules(api_package.__path__):
        router = getattr(importlib.import_module(f"nevo.api.{module.name}"), "router", None)
        for route in getattr(router, "routes", []):
            methods = getattr(route, "methods", None) or set()
            if getattr(route, "path", None) == path and method.upper() in methods:
                return route
    return None


def _dependency_names(route: object) -> set[str]:
    names: set[str] = set()
    stack = list(route.dependant.dependencies)  # type: ignore[attr-defined]
    while stack:
        dependency = stack.pop()
        if dependency.call is not None:
            names.add(getattr(dependency.call, "__name__", ""))
        stack.extend(dependency.dependencies)
    return names
