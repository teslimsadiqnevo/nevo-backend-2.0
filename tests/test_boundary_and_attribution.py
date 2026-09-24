"""Two things the client had and could not send or show.

The child answers the break offer at a module boundary and the answer was
dropped at the door: the client filters every event against a copy of our
enum before posting, because one unknown type refuses the whole batch. And a
note set by a teacher reached the child signed "Your teacher", because the
only names available were the lesson's author - a different person whenever
somebody assigns a colleague's lesson - and the class's teacher list.
"""

from __future__ import annotations

import pytest

from nevo.domain.signal_events.vocabulary import SignalEventType
from nevo.main import app


@pytest.fixture(scope="module")
def spec() -> dict:
    return app.openapi()


def test_what_a_child_did_at_a_boundary_can_be_reported() -> None:
    assert SignalEventType.MODULE_BOUNDARY_ACTION == "module_boundary_action"


def test_it_sits_beside_the_arrival_it_answers() -> None:
    # reached says a child got there; action says what they chose.
    assert SignalEventType.MODULE_BOUNDARY_REACHED in SignalEventType
    assert SignalEventType.MODULE_BOUNDARY_ACTION in SignalEventType


def test_the_database_learns_the_value_too() -> None:
    """A native Postgres enum does not follow the Python one on its own."""

    from pathlib import Path

    migration = Path("alembic/versions/20260924_0077_module_boundary_action.py").read_text()

    assert "ALTER TYPE signal_event_type ADD VALUE IF NOT EXISTS" in migration
    assert "module_boundary_action" in migration


def test_an_assignment_names_the_teacher_who_set_it(spec: dict) -> None:
    properties = spec["components"]["schemas"]["AssignmentResponse"]["properties"]

    assert "assignedByName" in properties
    assert "assignedById" in properties


def test_an_unresolvable_name_is_absent_rather_than_a_placeholder() -> None:
    """Naming the wrong teacher is worse than naming none."""

    import inspect

    from nevo.api.product_learning import _names_for

    source = inspect.getsource(_names_for)
    # The docstring names the placeholder as the thing to avoid, so check the
    # body rather than the whole function.
    body = source.split('"""')[-1]

    assert "Nevo user" not in body
    # Only a real name is recorded.
    assert "if name:" in body
