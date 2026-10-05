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
    LEGACY_STUDENT_PIN_DIGITS,
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
CHOOSERS = (PinChoice, PinUpdateRequest, JoinRequest)
UNLOCKERS = (PinLoginRequest, UnifiedLoginRequest)


def pin_schema(name: str) -> dict:
    schema = app.openapi()["components"]["schemas"][name]["properties"]["pin"]
    # The optional ones are a union with null; the constraint lives on the
    # string arm.
    for arm in schema.get("anyOf", [schema]):
        if arm.get("type") == "string":
            return arm
    raise AssertionError(f"{name} has no string arm on pin")


def test_new_pins_have_one_four_digit_shape() -> None:
    assert (STUDENT_PIN_MIN_DIGITS, STUDENT_PIN_MAX_DIGITS) == (4, 4)
    assert LEGACY_STUDENT_PIN_DIGITS == 6


def test_every_door_that_creates_a_pin_publishes_four_digits() -> None:
    shapes = {
        model.__name__: (
            pin_schema(model.__name__).get("minLength"),
            pin_schema(model.__name__).get("maxLength"),
            pin_schema(model.__name__).get("pattern"),
        )
        for model in CHOOSERS
    }

    assert len(set(shapes.values())) == 1, shapes
    assert set(shapes.values()) == {(4, 4, r"^\d+$")}


def test_the_four_digit_pin_is_accepted_everywhere() -> None:
    pin = "1234"
    PinChoice.model_validate({"pin": pin})
    PinLoginRequest.model_validate({"schoolCode": "ABC", "loginIdentifier": "ada", "pin": pin})
    PinUpdateRequest.model_validate({"pin": pin})
    JoinRequest.model_validate({"pin": pin})
    UnifiedLoginRequest.model_validate({"method": "pin", "pin": pin})


@pytest.mark.parametrize("pin", ["123", "12345", "1234567", "12345678", "12a4", "", "12 34"])
def test_what_is_refused_is_refused_everywhere(pin: str) -> None:
    for model in CARRIERS:
        with pytest.raises(ValidationError):
            model.model_validate({"pin": pin, "method": "pin"})


def test_an_administrator_no_longer_generates_a_pin_at_all() -> None:
    import inspect

    from nevo.api.product_admin import clear_student_pin

    # This used to mint four random digits and hand them to the adult who
    # asked, so an adult both chose a child's credential and knew it. Nobody
    # except the child ever sets a PIN now. SCRUM-216.
    source = inspect.getsource(clear_student_pin)
    assert "04d" not in source
    assert "randbelow" not in source
    assert "pin_hash = None" in source
    # Four digits is still the shape the child sets and the door accepts.
    PinLoginRequest.model_validate({"schoolCode": "ABC", "loginIdentifier": "ada", "pin": "0000"})


def test_a_legacy_six_digit_pin_can_only_unlock_for_migration() -> None:
    PinLoginRequest.model_validate({"schoolCode": "ABC", "loginIdentifier": "ada", "pin": "123456"})
    UnifiedLoginRequest.model_validate({"method": "pin", "pin": "123456"})
    for model in CHOOSERS:
        with pytest.raises(ValidationError):
            model.model_validate({"pin": "123456"})
