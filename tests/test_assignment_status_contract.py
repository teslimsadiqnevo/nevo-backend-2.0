"""Every status an assignment can be put into is a status it can be read in.

``completed`` was missing from AssignmentStatus, and the progress route has
written it since it was built. So the first child to finish a lesson made
GET /api/v1/assignments answer 500 for their whole school - the row was fine,
the response model was not, and it failed on the way out. A teacher could not
see or cancel anything they had assigned, and the trigger was a child doing
exactly what the product is for.

The test that would have caught it is the one below: read the values the code
writes out of the source, and check the vocabulary knows all of them.
"""

from __future__ import annotations

import re
from pathlib import Path

from nevo.domain.intelligence.vocabulary import AssignmentStatus
from nevo.main import app

#: Where an assignment's status is set, and where it is filtered on.
SOURCES = tuple(Path("src/nevo/api").glob("*.py")) + tuple(Path("src/nevo").glob("*/*.py"))

#: assignment.status = "..." / LessonAssignment.status != "..."
WRITES = re.compile(r"(?:assignment|LessonAssignment)\.status\s*(?:=|==|!=)\s*[\"']([a-z_]+)[\"']")


def written_values() -> set[str]:
    found: set[str] = set()
    for path in SOURCES:
        found.update(WRITES.findall(path.read_text()))
    return found


def test_the_code_writes_nothing_the_vocabulary_does_not_know() -> None:
    known = {status.value for status in AssignmentStatus}
    unknown = written_values() - known

    assert unknown == set(), f"written but not in AssignmentStatus: {sorted(unknown)}"


def test_completed_is_one_of_them() -> None:
    # The one that was missing, and the one a working product produces most.
    assert AssignmentStatus.COMPLETED == "completed"
    assert "completed" in written_values()


def test_the_published_enum_carries_all_three() -> None:
    schema = app.openapi()["components"]["schemas"]["AssignmentStatus"]

    assert set(schema["enum"]) == {"assigned", "completed", "cancelled"}


def test_a_completed_assignment_can_be_read_back() -> None:
    """The exact failure: a valid row that the response model refused."""

    from datetime import UTC, datetime
    from uuid import uuid4

    from nevo.api.response_models import AssignmentResponse

    response = AssignmentResponse.model_validate(
        {
            "id": str(uuid4()),
            "lesson": {
                "id": str(uuid4()),
                "title": "Water Cycle",
                "status": "completed_with_review",
                "sourceType": "text",
                "segmentCount": 5,
                "reviewSegmentCount": 5,
                "createdAt": datetime.now(UTC),
            },
            "studentId": str(uuid4()),
            "classId": None,
            "status": "completed",
            "dueAt": None,
            "availableFrom": None,
            "assignedAt": datetime.now(UTC),
        }
    )

    assert response.status is AssignmentStatus.COMPLETED
