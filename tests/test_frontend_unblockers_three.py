"""Three contracts the console was waiting on.

An adaptation-log type filter, a readable record of the rights parents have
exercised, and an academic config that says what Nevo does with it.
"""

from __future__ import annotations

from datetime import date

import pytest

from nevo.api.admin import AdaptationEventType
from nevo.api.product_admin import SchoolPatch
from nevo.api.response_models import AcademicConfig
from nevo.intelligence.adaptation_log import ADAPTATION_EVENT_TYPES
from nevo.main import app


def _operation(path: str, method: str = "get") -> dict:
    return app.openapi()["paths"][path][method]


class TestAdaptationLogFilter:
    def test_the_filter_is_offered(self) -> None:
        names = {p["name"] for p in _operation("/api/admin/adaptation-log")["parameters"]}
        assert "eventType" in names

    def test_a_client_can_see_what_it_may_ask_for(self) -> None:
        schema = app.openapi()["components"]["schemas"]["AdaptationEventType"]
        assert set(schema["enum"]) == {item.value for item in ADAPTATION_EVENT_TYPES}

    def test_the_filter_values_cannot_drift_from_the_log(self) -> None:
        # The enum is written out by hand so it appears in the schema; this is
        # what stops a new adaptation signal becoming unfilterable.
        assert {item.value for item in AdaptationEventType} == {
            item.value for item in ADAPTATION_EVENT_TYPES
        }


class TestRightsLog:
    PATH = "/api/v1/consents/rights-log"

    def test_the_log_is_readable(self) -> None:
        assert self.PATH in app.openapi()["paths"]

    def test_it_can_be_narrowed(self) -> None:
        names = {p["name"] for p in _operation(self.PATH)["parameters"]}
        assert {"studentId", "requestType", "limit", "offset"} <= names

    def test_it_does_not_serve_what_a_parent_wrote(self) -> None:
        # The reason is free text about a family. The log says one was given.
        fields = app.openapi()["components"]["schemas"]["ParentRightLogRow"]["properties"]
        assert "reasonRecorded" in fields
        assert "reason" not in fields


class TestAcademicConfig:
    def test_it_names_the_field_billing_reads(self) -> None:
        assert "term_start_dates" in AcademicConfig.model_fields

    def test_a_school_may_keep_its_own_keys(self) -> None:
        config = AcademicConfig.model_validate({"houseColours": ["red", "blue"]})
        assert config.model_dump(mode="json")["houseColours"] == ["red", "blue"]

    def test_an_unreadable_term_date_is_refused_rather_than_ignored(self) -> None:
        # It used to be swallowed with a log line, and the school was then
        # invoiced on dates it had not chosen.
        with pytest.raises(ValueError):
            SchoolPatch.model_validate({"academicConfig": {"termStartDates": ["last tuesday"]}})

    def test_term_dates_survive_the_write_as_iso_strings(self) -> None:
        # Billing parses them back with date.fromisoformat.
        patch = SchoolPatch.model_validate(
            {"academicConfig": {"termStartDates": ["2026-09-14", "2027-01-11", "2027-04-19"]}}
        )
        assert patch.academic_config is not None
        stored = patch.academic_config.model_dump(mode="json")["term_start_dates"]
        assert [date.fromisoformat(item) for item in stored] == [
            date(2026, 9, 14),
            date(2027, 1, 11),
            date(2027, 4, 19),
        ]

    def test_a_school_cannot_claim_more_terms_than_a_year_has(self) -> None:
        with pytest.raises(ValueError):
            AcademicConfig.model_validate(
                {"termStartDates": ["2026-09-14", "2027-01-11", "2027-04-19", "2027-07-01"]}
            )
