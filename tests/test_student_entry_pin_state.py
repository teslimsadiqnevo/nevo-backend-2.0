from __future__ import annotations

import inspect
from types import SimpleNamespace

from nevo.api.student_entry import _pin_state, set_own_pin
from nevo.main import app


def test_entry_reports_all_three_pin_states() -> None:
    assert _pin_state(SimpleNamespace(pin_hash=None, pin_cleared_at=None)) == "not_set"
    assert _pin_state(SimpleNamespace(pin_hash=None, pin_cleared_at=object())) == "cleared"
    assert _pin_state(SimpleNamespace(pin_hash="hash", pin_cleared_at=None)) == "set"


def test_first_pin_and_cleared_pin_use_the_same_route() -> None:
    source = inspect.getsource(set_own_pin)

    assert "student.pin_hash is not None" in source
    assert "student.pin_cleared_at is None" not in source


def test_lookup_contract_carries_the_routing_state() -> None:
    schema = app.openapi()
    fields = schema["components"]["schemas"]["StudentEntryState"]["properties"]

    assert fields["pinState"]["enum"] == ["not_set", "cleared", "set"]
