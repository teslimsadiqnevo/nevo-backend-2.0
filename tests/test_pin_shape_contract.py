"""One PIN shape on every door, because the short one is a lockout.

The doors where a PIN is chosen were relaxed to four-to-eight digits and the
doors where one is checked were left at exactly six. A child given a
four-digit PIN at entry could therefore never sign in: every attempt was a
422, and the client classifies a 422 as our fault, so they were told we could
not check it just now rather than that anything was wrong with the PIN.

These tests hold every door to the same shape. A relaxation on one side that
does not reach the other fails here rather than in a classroom.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nevo.api.auth import (
    STUDENT_PIN_MAX_DIGITS,
    STUDENT_PIN_MIN_DIGITS,
    PinLoginRequest,
    UnifiedLoginRequest,
)
from nevo.api.product_auth import JoinRequest, PinUpdateRequest
from nevo.api.student_entry import PinChoice
from nevo.main import app

#: Every model carrying a child's PIN: the two that set one, the three that
#: check one.
CARRIERS = (PinChoice, PinLoginRequest, PinUpdateRequest, JoinRequest, UnifiedLoginRequest)


def pin_schema(name: str) -> dict:
    schema = app.openapi()["components"]["schemas"][name]["properties"]["pin"]
    # The optional ones are a union with null; the constraint lives on the
    # string arm.
    for arm in schema.get("anyOf", [schema]):
        if arm.get("type") == "string":
            return arm
    raise AssertionError(f"{name} has no string arm on pin")


def test_design_settled_on_four_to_eight() -> None:
    assert (STUDENT_PIN_MIN_DIGITS, STUDENT_PIN_MAX_DIGITS) == (4, 8)


def test_every_door_publishes_the_same_shape() -> None:
    shapes = {
        model.__name__: (
            pin_schema(model.__name__).get("minLength"),
            pin_schema(model.__name__).get("maxLength"),
            pin_schema(model.__name__).get("pattern"),
        )
        for model in CARRIERS
    }

    assert len(set(shapes.values())) == 1, shapes
    assert set(shapes.values()) == {(4, 8, r"^\d+$")}


@pytest.mark.parametrize("pin", ["1234", "123456", "12345678"])
def test_a_pin_accepted_where_it_is_chosen_is_accepted_where_it_is_checked(pin: str) -> None:
    # The four-digit case is the one that locked children out.
    PinChoice.model_validate({"pin": pin})
    PinLoginRequest.model_validate({"schoolCode": "ABC", "loginIdentifier": "ada", "pin": pin})
    PinUpdateRequest.model_validate({"pin": pin})
    JoinRequest.model_validate({"pin": pin})
    UnifiedLoginRequest.model_validate({"method": "pin", "pin": pin})


@pytest.mark.parametrize("pin", ["123", "123456789", "12a456", "", "12 456"])
def test_what_is_refused_is_refused_everywhere(pin: str) -> None:
    for model in CARRIERS:
        with pytest.raises(ValidationError):
            model.model_validate({"pin": pin, "method": "pin"})


def test_an_administrators_generated_reset_still_fits() -> None:
    # Six digits, unchanged, and still inside the shared range.
    import inspect

    from nevo.api.product_admin import issue_student_pin

    assert "06d" in inspect.getsource(issue_student_pin)
    PinLoginRequest.model_validate({"schoolCode": "ABC", "loginIdentifier": "ada", "pin": "000000"})
