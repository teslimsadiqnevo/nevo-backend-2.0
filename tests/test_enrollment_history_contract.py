"""Enrolment writes a history row, and the row has to be constructible.

`POST /api/v1/students` and `PATCH /api/v1/students/{id}/class` both passed a
school_id to EnrollmentHistory, which has no such column. Every call to either
raised TypeError before it reached the database, so both endpoints returned
500 for every request ever made to them. Nothing caught it because nothing
constructed the model.
"""

from __future__ import annotations

import inspect
from uuid import uuid4

import pytest

from nevo.api import product_admin
from nevo.db.models.product import EnrollmentHistory


def test_the_history_row_an_enrolment_writes_can_be_built() -> None:
    row = EnrollmentHistory(
        student_id=uuid4(),
        to_class_id=uuid4(),
        action="enrolled",
        actor_user_id=uuid4(),
    )
    assert row.action == "enrolled"


def test_the_history_row_a_move_writes_can_be_built() -> None:
    row = EnrollmentHistory(
        student_id=uuid4(),
        from_class_id=uuid4(),
        to_class_id=uuid4(),
        action="moved",
        actor_user_id=uuid4(),
    )
    assert row.action == "moved"


@pytest.mark.parametrize("handler", ["enroll_student", "move_student"])
def test_no_handler_passes_a_column_the_model_does_not_have(handler: str) -> None:
    # The fault was invisible in review because the keyword looked plausible.
    # Anything the mapper does not know about raises at construction.
    known = set(EnrollmentHistory.__mapper__.attrs.keys())
    source = inspect.getsource(getattr(product_admin, handler))
    block = source.split("EnrollmentHistory(", 1)[1].split(")", 1)[0]
    passed = {
        line.split("=", 1)[0].strip()
        for line in block.splitlines()
        if "=" in line and not line.strip().startswith("#")
    }
    assert passed, handler
    assert passed <= known, f"{handler} passes {sorted(passed - known)}"
