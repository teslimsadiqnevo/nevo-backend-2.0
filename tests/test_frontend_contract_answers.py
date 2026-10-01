"""The contract complaints from 21 September, and what each is now.

Every one of these is a claim a client made about the API that could be
checked, so each is checked here rather than answered in a message.
"""

from __future__ import annotations

import inspect

import pytest

from nevo.api.sso import CREDENTIAL_WARNING
from nevo.main import app


@pytest.fixture(scope="module")
def spec() -> dict:
    return app.openapi()


def test_class_insight_state_is_required(spec: dict) -> None:
    schema = spec["components"]["schemas"]["ClassInsightsNarrativeResponse"]

    # It shipped with a default, which makes it optional in the schema: a
    # client could not rely on it and was back to inferring the state from
    # the length of an array, which is what the field exists to stop.
    assert "state" in schema["required"]


def test_the_two_narrative_strings_are_never_absent(spec: dict) -> None:
    schema = spec["components"]["schemas"]["ClassInsightsNarrativeResponse"]

    # Deliberately not nullable. A quiet week is a finding, said in words;
    # a null would read as missing data. Branch on state, not on absence.
    assert {"weeklySummary", "lookingAhead"} <= set(schema["required"])
    for field in ("weeklySummary", "lookingAhead"):
        assert schema["properties"][field]["type"] == "string"


def test_a_school_can_read_back_who_a_document_was_shared_with(spec: dict) -> None:
    # "Who has seen my child's record" is a question a parent asks and a
    # regulator asks. The shares were written and never readable.
    assert "get" in spec["paths"]["/api/v1/exports/iep/{export_id}/shares"]


def test_sso_health_warns_before_the_credential_expires(spec: dict) -> None:
    fields = spec["components"]["schemas"]["SsoConnectionHealthResponse"]["properties"]

    assert {
        "credentialExpiresAt",
        "credentialExpiresInDays",
        "credentialExpiringSoon",
    } <= set(fields)
    # Long enough for a school to raise a ticket with its own IT and have it
    # done, since renewing the secret is their job rather than ours.
    assert CREDENTIAL_WARNING.days >= 30


def test_enrolling_a_student_cannot_collide_on_an_email_it_never_takes() -> None:
    from nevo.api.product_admin import StudentEnroll, enroll_student

    source = inspect.getsource(enroll_student)

    # users.email is unique across the product, and an empty string sent for
    # two children used to collide on the second and come back as a server
    # fault. The normalisation that fixed it is gone because the field is:
    # enrolment no longer asks for a child's email at all, since children do
    # not have one and asking was why schools were inventing them. SCRUM-202.
    assert "email" not in StudentEnroll.model_fields
    # The collision is still named rather than raised as a 500, because the
    # admission number is unique per school and can collide the same way.
    assert "IntegrityError" in source
    assert "admission_number_in_use" in source


def test_an_unexpected_error_carries_something_to_trace_it_by() -> None:
    from nevo.main import unexpected_error_handler

    source = inspect.getsource(unexpected_error_handler)

    # "Two unexplained 500s" was the most anybody could report, because the
    # response carried nothing and the log carried no id.
    assert "incidentId" in source
    assert "logger.exception" in source


def test_a_fourth_term_date_is_refused_rather_than_dropped() -> None:
    import pydantic

    from nevo.api.response_models import MAX_TERM_START_DATES, AcademicConfig

    assert MAX_TERM_START_DATES == 3
    assert AcademicConfig.model_json_schema()["properties"]["termStartDates"]["maxItems"] == 3

    # Billing issues one invoice per term start, so a fourth date is a fourth
    # invoice. Keeping the first three would bill a school on a calendar it
    # never configured, so the whole request is refused - and the message says
    # why, rather than "List should have at most 3 items".
    four = ["2026-09-14", "2027-01-11", "2027-04-19", "2027-07-01"]
    try:
        AcademicConfig.model_validate({"termStartDates": four})
    except pydantic.ValidationError as error:
        assert "invoice" in error.errors()[0]["msg"]
    else:  # pragma: no cover - the point of the test
        raise AssertionError("a fourth term date was accepted")

    three = AcademicConfig.model_validate({"termStartDates": four[:3]})
    assert len(three.term_start_dates) == 3
