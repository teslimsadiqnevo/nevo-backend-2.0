from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nevo.api.auth import optional_authenticated_principal
from nevo.api.client_errors import router
from nevo.auth.entities import AuthPrincipal


def test_crash_logs_do_not_contain_browser_text_or_account_identifiers(caplog):
    app = FastAPI()
    user_id = uuid4()
    app.dependency_overrides[optional_authenticated_principal] = lambda: AuthPrincipal(
        user_id, "student", uuid4()
    )
    app.include_router(router)
    payload = {
        "message": "TypeError: A child's private answer",
        "stack": "secret question text",
        "route": "/student/private-child?token=secret",
        "appVersion": "private@example.com",
        "surface": "student",
        "incidentId": "private-name",
    }
    response = TestClient(app).post("/api/v1/client-errors", json=payload)
    assert response.status_code == 202, response.text
    assert len(response.json()["incidentId"]) == 12
    entries = [record.__dict__ for record in caplog.records if record.name == "nevo.client_errors"]
    assert len(entries) == 1
    recorded = str(entries)
    for private in (
        "private answer",
        "secret question",
        "private-child",
        "private@example.com",
        "private-name",
        str(user_id),
    ):
        assert private not in recorded
    assert entries[0]["error_kind"] == "TypeError"
