"""Cohort figures, and no way to ask for a child's.

A self-regulation index against a named child is a score about a person. The
endpoint that would return one was struck out, and this checks it cannot be
built back by accident - along with the ruling that three true indicators beat
four where one is invented.
"""

from __future__ import annotations

import inspect

import pytest

from nevo.api import transformation_metrics
from nevo.api.transformation_metrics import REPORTING_FLOOR, _trend
from nevo.main import app


@pytest.fixture(scope="module")
def spec() -> dict:
    return app.openapi()


def test_there_is_a_class_and_a_school_endpoint(spec: dict) -> None:
    assert "get" in spec["paths"]["/api/metrics/transformation/class/{class_id}"]
    assert "get" in spec["paths"]["/api/metrics/transformation/school/{school_id}"]


def test_there_is_no_per_student_endpoint(spec: dict) -> None:
    # Struck out of SCRUM-74. Whatever is built here must be incapable of
    # returning one learner's figures.
    paths = [path for path in spec["paths"] if "metrics/transformation" in path]

    assert all("student" not in path for path in paths)
    assert "/api/metrics/transformation/{student_id}" not in spec["paths"]


def test_nothing_in_the_module_queries_a_single_learner() -> None:
    source = inspect.getsource(transformation_metrics)

    # Every scope resolves to a list of learners and every figure groups.
    assert "student_id ==" not in source


def test_a_cohort_too_small_to_report_is_suppressed_not_shown() -> None:
    assert REPORTING_FLOOR >= 5
    source = inspect.getsource(transformation_metrics._metrics)

    assert "suppressed=True" in source


def test_calibration_says_why_it_is_missing_rather_than_inventing_a_number(
    spec: dict,
) -> None:
    fields = spec["components"]["schemas"]["Unavailable"]["properties"]

    assert {"reason", "needed"} <= set(fields)
    unavailable = transformation_metrics._calibration_is_not_measurable()
    assert unavailable.available is False
    assert "how sure" in unavailable.needed


def test_the_three_that_are_computed_come_from_signals_we_record() -> None:
    for name in ("_self_regulation", "_efficiency", "_flexibility"):
        source = inspect.getsource(getattr(transformation_metrics, name))

        # Each one names its signal in its own docstring, so a reader can
        # check the claim without leaving the file.
        assert "Signal:" in source


@pytest.mark.parametrize(
    ("value", "previous", "higher_is_better", "expected"),
    [
        (80.0, 60.0, True, "up"),
        (60.0, 80.0, True, "down"),
        (18.0, 24.0, False, "up"),
        (24.0, 18.0, False, "down"),
        (50.0, 50.4, True, "steady"),
        (50.0, None, True, "unknown"),
    ],
)
def test_a_trend_reads_the_right_way_round(
    value: float,
    previous: float | None,
    higher_is_better: bool,
    expected: str,
) -> None:
    # Less time on a lesson a learner still finished is better, not worse.
    assert _trend(value, previous, higher_is_better=higher_is_better) == expected


def test_the_response_carries_its_own_cohort_size(spec: dict) -> None:
    fields = spec["components"]["schemas"]["TransformationMetrics"]["properties"]

    assert {"learnerCount", "reportingFloor", "suppressed"} <= set(fields)
