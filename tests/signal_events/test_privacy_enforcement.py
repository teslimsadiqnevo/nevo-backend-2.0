from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from nevo.consent.errors import ConsentWithdrawnError
from tests.signal_events.test_api import client_for


def batch(extra=None):
    session_id = str(uuid4())
    return {
        "session": {"sessionId": session_id, "startedAt": "2026-10-20T12:00:00Z"},
        "events": [{"sessionId": session_id, "eventType": "scroll", **(extra or {})}],
    }


@pytest.mark.parametrize(
    "extra",
    [
        {"tapLatency": 25},
        {"eventData": {"metadata": {"tapDuration": 25}}},
        {"eventData": {"metadata": [{"screenX": 30}]}},
        {"eventData": {"points": [{"x": 30, "y": 40}]}},
        {"eventData": {"metadata": {"pressure": 0.5}}},
        {"eventData": {"metadata": {"keyStrokes": "private input"}}},
    ],
)
def test_raw_measurements_are_rejected_in_nested_and_flattened_payloads(extra):
    client, repository, _ = client_for()
    response = client.post("/api/signals/", json=batch(extra))
    assert response.status_code == 422
    assert repository.batches == []


@pytest.mark.parametrize(
    "mode,status,code",
    [
        ("missing", 503, "consent_service_unavailable"),
        ("down", 503, "consent_service_unavailable"),
        ("withdrawn", 403, "consent_withdrawn"),
    ],
)
def test_consent_cannot_fail_open(mode, status, code):
    client, repository, _ = client_for()
    if mode == "missing":
        del client.app.state.consent_service
    else:
        error = ConsentWithdrawnError() if mode == "withdrawn" else RuntimeError("unavailable")
        client.app.state.consent_service = SimpleNamespace(
            require_student_consent=AsyncMock(side_effect=error)
        )
    response = client.post("/api/signals/", json=batch())
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code
    assert repository.batches == []
