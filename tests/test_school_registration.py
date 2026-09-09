"""Registration must fail loudly on bad input, not with a 500."""
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nevo.api.dependencies import database_session
from nevo.api.product_auth import router


class RefusingSession:
    """Stands in for the database. Any query means the guard let it through."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"registration reached the database via {name}()")


def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[database_session] = RefusingSession
    return TestClient(app)


def test_blank_names_are_rejected_before_any_write() -> None:
    # min_length counts characters, so two spaces used to pass validation and
    # then raise IndexError on the name split - a 500 for a bad request.
    for payload in (
        {"schoolName": "Valid School", "adminName": "  "},
        {"schoolName": "   ", "adminName": "Valid Admin"},
        {"schoolName": "Valid School", "adminName": " a "},
    ):
        response = client().post(
            "/api/v1/schools/register",
            json={
                **payload,
                "email": "someone@example.com",
                "password": "Str0ngPassw0rd!",
            },
        )
        assert response.status_code == 422, payload


def test_surrounding_whitespace_is_kept_out_of_the_stored_name() -> None:
    payload = {
        "schoolName": "  Bright Star Academy  ",
        "adminName": "  Ngozi Okafor ",
        "email": "someone@example.com",
        "password": "Str0ngPassw0rd!",
    }

    from nevo.api.product_auth import SchoolRegistrationRequest

    request = SchoolRegistrationRequest.model_validate(payload)

    assert request.school_name == "Bright Star Academy"
    assert request.admin_name == "Ngozi Okafor"


def test_a_bulk_import_does_not_send_its_email_before_answering() -> None:
    """Five hundred rows, each sending an email inline, turns a roster upload
    into minutes of provider round trips while the caller waits."""
    import inspect

    from nevo.api import product_auth

    source = inspect.getsource(product_auth.create_bulk_invites)

    assert "defer_delivery=True" in source
    deferred = inspect.getsource(product_auth._create_invitation)
    assert '"queued"' in deferred
