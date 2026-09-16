"""A teacher clears a lesson before children see it.

SCRUM-37 has said since it was designed that approval is manual and deliberate
and that the teacher stays in control of what reaches students. The backend had
no write for it, so every lesson was in effect approved the moment it finished
parsing and the screen was advice a teacher could walk straight past.
"""

from __future__ import annotations

import inspect

import pytest

from nevo.api.product_common import require_approved_lessons
from nevo.db.models.content import LessonSegment
from nevo.main import app

APPROVE = "/api/v1/lessons/{lesson_id}/segments/{segment_id}/approve"


@pytest.fixture(scope="module")
def spec() -> dict:
    return app.openapi()


def test_a_segment_can_be_approved(spec: dict) -> None:
    assert APPROVE in spec["paths"]
    assert "post" in spec["paths"][APPROVE]


def test_approving_says_whether_the_lesson_is_now_assignable(spec: dict) -> None:
    # The screen walks a lesson a segment at a time and has to know when it
    # has reached the end, without a second read to find out.
    fields = spec["components"]["schemas"]["SegmentApprovalResponse"]["properties"]

    assert {"approvedSegmentCount", "segmentCount", "lessonApproved"} <= set(fields)


def test_a_segment_read_says_whether_it_is_approved(spec: dict) -> None:
    fields = spec["components"]["schemas"]["LessonSegmentResponse"]["properties"]

    assert "approved" in fields
    assert "approvedAt" in fields


def test_the_column_records_who_approved_and_when() -> None:
    columns = {c.name for c in LessonSegment.__table__.columns}

    assert {"approved_at", "approved_by"} <= columns


@pytest.mark.parametrize(
    "handler",
    [
        ("nevo.api.frontend_unblockers", "create_lesson_assignments"),
        ("nevo.api.product_learning", "create_assignments"),
    ],
    ids=["one lesson", "several at once"],
)
def test_every_route_to_an_assignment_is_gated(handler: tuple[str, str]) -> None:
    # There are two doors to assignment. A gate on one is not a gate.
    import importlib

    module = importlib.import_module(handler[0])
    source = inspect.getsource(getattr(module, handler[1]))

    assert "require_approved_lessons" in source


def test_the_gate_is_one_implementation() -> None:
    source = inspect.getsource(require_approved_lessons)

    assert "approved_at.is_(None)" in source
    assert "409" in source or "HTTP_409_CONFLICT" in source


def test_it_names_which_lessons_and_how_much_is_left() -> None:
    # "Refused" is not actionable. Which lesson, and how many segments, is.
    source = inspect.getsource(require_approved_lessons)

    assert "unapprovedSegmentCount" in source
    assert "lesson_not_approved" in source
