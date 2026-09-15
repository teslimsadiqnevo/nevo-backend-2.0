"""One spelling on the wire, and no broken writes on the way there.

Thirty-eight schemas kept their Python field names while the rest of the API
spoke camelCase. A client could not tell which was which from the outside, so
`accessToken` read as undefined and the mistake looked like an auth failure.

Responses are camelCase now, which is a breaking change for anything reading
the old spelling. Requests are not: the models still accept their Python
names, so a client that has not caught up keeps working.
"""

from __future__ import annotations

import re

import pytest

from nevo.api.auth import PinLoginRequest, SessionResponse
from nevo.api.casing import to_camel
from nevo.api.consent import ParentConsentRequest
from nevo.api.teacher_assignments import CreateAssignmentRequest
from nevo.main import app

SNAKE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)+$")


@pytest.fixture(scope="module")
def schemas() -> dict:
    return app.openapi()["components"]["schemas"]


def test_nothing_on_the_wire_is_snake_case(schemas: dict) -> None:
    offenders = {
        name: [field for field in schema.get("properties", {}) if SNAKE.match(field)]
        for name, schema in schemas.items()
    }
    assert not {name: bad for name, bad in offenders.items() if bad}


def test_no_schema_is_named_after_its_python_module(schemas: dict) -> None:
    # Two classes sharing a name made the generated client call one of them
    # nevo__api__response_models__AssignmentResponse.
    assert [name for name in schemas if "__" in name] == []


@pytest.mark.parametrize(
    ("model", "body"),
    [
        (PinLoginRequest, {"school_code": "NVS", "login_identifier": "UZ59R", "pin": "244300"}),
        (
            CreateAssignmentRequest,
            {
                "teacher_id": "8d2f4b7e-0000-4000-8000-000000000001",
                "class_id": "8d2f4b7e-0000-4000-8000-000000000002",
                "role": "primary",
            },
        ),
    ],
)
def test_a_client_still_sending_snake_case_is_not_broken(model: type, body: dict) -> None:
    assert model.model_validate(body)


def test_the_same_body_in_camel_case_means_the_same_thing() -> None:
    snake = PinLoginRequest.model_validate(
        {"school_code": "NVS", "login_identifier": "UZ59R", "pin": "244300"}
    )
    camel = PinLoginRequest.model_validate(
        {"schoolCode": "NVS", "loginIdentifier": "UZ59R", "pin": "244300"}
    )
    assert snake == camel


def test_responses_go_out_in_camel_case() -> None:
    body = ParentConsentRequest.model_validate(
        {
            "parent_name": "A Parent",
            "parent_contact": "parent@example.test",
            "contact_method": "email",
        }
    ).model_dump(by_alias=True)
    assert "parentName" in body
    assert "parent_name" not in body


def test_the_token_field_that_started_this_is_camel() -> None:
    assert SessionResponse.model_fields["access_token"].alias == "accessToken"


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("access_token", "accessToken"),
        ("ai_gateway_call_id", "aiGatewayCallId"),
        ("school_url_slug", "schoolUrlSlug"),
        ("role", "role"),
    ],
)
def test_the_conversion_itself(field: str, expected: str) -> None:
    assert to_camel(field) == expected
