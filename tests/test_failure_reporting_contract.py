"""A failure says one thing to a teacher and another thing to us.

Both doors into the parse pipeline recorded only what the driver said, and on
the content route that went out under the name ``failureReason`` - a field
whose name promises prose and which delivered the first line of a stack
trace. A console rendered it verbatim, so a school owner read a Postgres
error. And neither door carried a reference, so a teacher looking at a failed
parse had nothing to quote.
"""

from __future__ import annotations

import pytest

from nevo.content_parsing.failures import (
    GENERIC_FAILURE,
    failure_reason,
    new_incident,
)
from nevo.main import app


@pytest.fixture(scope="module")
def spec() -> dict:
    return app.openapi()


def test_the_missing_column_that_started_this_reads_as_our_fault() -> None:
    sentence = failure_reason(
        'UndefinedColumnError: column "depth_variants" of relation "lesson_segments" does not exist'
    )

    assert sentence != GENERIC_FAILURE
    assert "our end" in sentence
    # Never the words the driver used.
    assert "depth_variants" not in sentence
    assert "relation" not in sentence


@pytest.mark.parametrize(
    ("raw", "expected_marker"),
    [
        ("No readable lesson text was found", "selectable text"),
        ("httpx.ReadTimeout: timed out", "splitting it"),
        ("Provider returned 429 too many requests", "a few minutes"),
    ],
)
def test_a_cause_we_recognise_says_what_to_do_next(raw: str, expected_marker: str) -> None:
    assert expected_marker in failure_reason(raw)


def test_anything_unrecognised_says_so_rather_than_guessing() -> None:
    # A guess dressed as a diagnosis sends a teacher to fix the wrong thing.
    assert failure_reason("ValueError: something nobody has seen before") == GENERIC_FAILURE


def test_a_reference_is_twelve_lowercase_hex() -> None:
    incident = new_incident()

    assert len(incident) == 12
    assert incident == incident.lower()
    assert all(char in "0123456789abcdef" for char in incident)
    assert new_incident() != incident


def test_both_doors_report_a_failure_the_same_way(spec: dict) -> None:
    staged = spec["components"]["schemas"]["UploadStatusResponse"]["properties"]
    content = spec["components"]["schemas"]["ParseRunResponse"]["properties"]

    for shape in (staged, content):
        # Prose for the screen, raw for us, and a reference for both.
        assert "failureReason" in shape
        assert "error" in shape
        assert "incidentId" in shape


def test_the_raw_text_is_never_what_failure_reason_carries() -> None:
    import inspect

    from nevo.content_parsing.repositories import SqlAlchemyContentParsingRepository

    source = inspect.getsource(SqlAlchemyContentParsingRepository.run_state)

    # It used to be failure_reason=run.error_message.
    assert "failure_reason=run.failure_reason" in source
    assert "failure_reason=run.error_message" not in source


def test_a_failed_run_is_given_a_reference_when_it_fails() -> None:
    import inspect

    from nevo.content_parsing.service import ContentParsingService

    source = inspect.getsource(ContentParsingService._run)

    assert "new_incident()" in source
    assert "incident_id=incident" in source
    assert "failure_reason=failure_reason(error)" in source


def test_a_batch_can_be_polled_in_one_request(spec: dict) -> None:
    """Twenty files were twenty polls every few seconds."""

    listing = spec["paths"]["/api/v1/uploads"]["get"]
    names = {parameter["name"] for parameter in listing.get("parameters", [])}

    assert names == {"limit", "unsettledOnly"}
