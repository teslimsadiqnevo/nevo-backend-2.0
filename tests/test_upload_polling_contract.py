"""A job can be polled from the moment it is created.

GET /api/v1/uploads/{id} answered 500 for the entire window it exists to
report on. A freshly created job carries an empty structure, and the response
model required a lessonId and a modules list inside it, so validation failed
on the way out - a 500 with no incident id the client could act on, on the one
route a teacher's processing screen polls.

The fix is not a default value. It is that an upload which is still parsing
genuinely has no lesson yet, and the contract has to be able to say so.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from nevo.api.response_models import (
    UploadStatusResponse,
    UploadStructureDocument,
)
from nevo.domain.intelligence.vocabulary import UploadStage, UploadStatus
from nevo.main import app

#: Exactly what the database holds for a job created a second ago.
FRESH_JOB = {
    "id": str(uuid4()),
    "status": "processing",
    "stage": "lessons",
    "lessonTitle": None,
    "segments": [],
    "failedPages": [],
    "structure": {},
    "error": None,
}


def test_a_job_that_has_only_just_started_can_be_read() -> None:
    response = UploadStatusResponse.model_validate(FRESH_JOB)

    assert response.status is UploadStatus.PROCESSING
    assert response.structure.lesson_id is None
    assert response.structure.modules == []
    assert response.structure.lessons == []


def test_nothing_inside_the_structure_is_required() -> None:
    # An empty object is a valid answer, because it is a true one.
    assert UploadStructureDocument.model_validate({}).lesson_id is None
    assert app.openapi()["components"]["schemas"]["UploadStructureDocument"].get("required") is None


def test_a_failed_job_can_be_read_too() -> None:
    response = UploadStatusResponse.model_validate(
        {**FRESH_JOB, "status": "failed", "error": "Something went wrong during the parse"}
    )

    # The failure has to be readable, or the only way to learn a parse died is
    # that a lesson never appears.
    assert response.status is UploadStatus.FAILED
    assert response.error is not None


def test_a_finished_job_still_carries_the_lesson() -> None:
    lesson_id = str(uuid4())
    response = UploadStatusResponse.model_validate(
        {
            **FRESH_JOB,
            "status": "ready",
            "stage": "structure",
            "structure": {"lessonId": lesson_id, "modules": [], "lessons": []},
        }
    )

    assert str(response.structure.lesson_id) == lesson_id


def test_the_status_is_what_says_whether_a_lesson_exists() -> None:
    # Not the presence of lessonId: a client that branches on the id will read
    # "still parsing" and "parse failed" as the same thing.
    assert set(UploadStatus) >= {UploadStatus.PROCESSING, UploadStatus.READY, UploadStatus.FAILED}


@pytest.mark.parametrize("missing", ["status", "stage", "id"])
def test_the_fields_that_are_always_true_stay_required(missing: str) -> None:
    payload = {key: value for key, value in FRESH_JOB.items() if key != missing}

    with pytest.raises(ValidationError):
        UploadStatusResponse.model_validate(payload)


def test_the_longest_wait_has_a_stage_of_its_own() -> None:
    """Named by the console: "Preparing the adaptations"."""

    assert UploadStage.ADAPTATIONS == "adaptations"
    # Ordered as a teacher meets them.
    assert list(UploadStage) == [
        UploadStage.LESSONS,
        UploadStage.STRUCTURE,
        UploadStage.ADAPTATIONS,
        UploadStage.COMPLETE,
    ]
    assert app.openapi()["components"]["schemas"]["UploadStage"]["enum"] == [
        "lessons",
        "structure",
        "adaptations",
        "complete",
    ]


def test_the_parser_reports_that_stage_before_it_makes_the_media() -> None:
    import inspect

    from nevo.content_parsing.service import ContentParsingService

    source = inspect.getsource(ContentParsingService.parse)

    assert "UploadStage.ADAPTATIONS" in source
    assert source.index("UploadStage.ADAPTATIONS") < source.index("_generate_media")


def test_a_progress_report_that_fails_does_not_cost_the_lesson() -> None:
    import inspect

    from nevo.content_parsing import service

    source = inspect.getsource(service._report)

    assert "except Exception" in source
