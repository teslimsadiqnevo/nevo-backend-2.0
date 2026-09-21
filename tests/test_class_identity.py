"""A class is one class, and it belongs to a school year.

Two spellings of one name is a class's children split between two rosters with
nobody told, and a name without a year is next September's JSS 1A colliding
with this one's. Both now matter more, because class names arrive out of a
school's own uploaded file rather than being typed once by hand.
"""

from __future__ import annotations

from datetime import date

import pytest

from nevo.db.models.account import Class
from nevo.domain.accounts.classes import (
    academic_session,
    normalise_class_name,
    parse_class_name,
)
from nevo.main import app


@pytest.fixture(scope="module")
def spec() -> dict:
    return app.openapi()


@pytest.mark.parametrize("written", ["JSS 1A", "jss 1a", "JSS 1A ", "  JSS  1A", "Jss  1a "])
def test_one_class_however_a_school_types_it(written: str) -> None:
    assert normalise_class_name(written) == "jss 1a"


def test_a_name_that_differs_in_more_than_spacing_is_another_class() -> None:
    assert normalise_class_name("JSS 1A") != normalise_class_name("JSS 1B")


@pytest.mark.parametrize(
    ("written", "year_group", "section"),
    [
        ("JSS 2A", "JSS 2", "A"),
        ("JSS 2 A", "JSS 2", "A"),
        ("JSS 2", "JSS 2", None),
        ("Primary 4B", "Primary 4", "B"),
        ("SS 3", "SS 3", None),
    ],
)
def test_a_class_name_carries_its_year_group_and_section(
    written: str,
    year_group: str | None,
    section: str | None,
) -> None:
    parsed = parse_class_name(written)

    assert parsed.year_group == year_group
    assert parsed.section == section


def test_a_school_may_name_a_class_anything() -> None:
    # Refusing "Sunflower" would be inventing a rule no school agreed to.
    parsed = parse_class_name("Sunflower")

    assert parsed.name == "Sunflower"
    assert parsed.year_group is None


@pytest.mark.parametrize(
    ("on", "session"),
    [
        (date(2026, 9, 1), "2026/2027"),
        (date(2026, 12, 31), "2026/2027"),
        (date(2027, 3, 15), "2026/2027"),
        (date(2027, 8, 31), "2026/2027"),
        (date(2027, 9, 1), "2027/2028"),
    ],
)
def test_the_school_year_runs_from_september(on: date, session: str) -> None:
    assert academic_session(on) == session


def test_the_compared_name_is_written_for_the_caller() -> None:
    # Set by a listener rather than at each call site, because there are now
    # three of them and a caller that forgets is a second JSS 1A.
    row = Class(school_id=None, name="  JSS   1a ")

    from nevo.db.models.account import _class_name_is_normalised

    _class_name_is_normalised(None, None, row)

    assert row.name == "JSS 1a"
    assert row.normalised_name == "jss 1a"
    assert row.academic_session


def test_uniqueness_is_per_school_per_session_and_ignores_archived() -> None:
    index = next(
        item for item in Class.__table__.indexes if item.name == "uq_classes_school_session_name"
    )

    assert index.unique
    assert [column.name for column in index.columns] == [
        "school_id",
        "academic_session",
        "normalised_name",
    ]
    assert "archived_at IS NULL" in str(index.dialect_options["postgresql"]["where"])


def test_a_class_can_be_created_one_at_a_time_or_a_grid_at_once(spec: dict) -> None:
    assert "post" in spec["paths"]["/api/v1/classes"]
    assert "post" in spec["paths"]["/api/v1/classes/bulk"]


def test_a_rejected_row_says_which_row_and_why(spec: dict) -> None:
    # A school creating thirty classes will not notice a count of failures.
    fields = spec["components"]["schemas"]["ClassRejection"]["properties"]

    assert {"index", "field", "value", "reason"} <= set(fields)


def test_the_listing_carries_what_the_console_groups_by(spec: dict) -> None:
    fields = spec["components"]["schemas"]["ClassSummaryResponse"]["properties"]

    assert {"section", "academicSession", "capacity", "teacherCount"} <= set(fields)
