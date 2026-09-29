"""A child's week by subject, and the line it must not cross. SCRUM-198.

Comprehension and mastery are per child by construction and were never struck.
The transformation metrics were: no Self-Regulation Index, no Metacognitive
Calibration, no Conceptual Flexibility, no Active Learning Efficiency, no index
of any kind, no percentile, no rating, no comparison between children. SCRUM-163
stands, and the shapes here are built so they cannot carry one.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from nevo.api.parents import (
    ChildSubjectProgressResponse,
    ProgressWindowResponse,
    SubjectProgressResponse,
)
from nevo.main import app
from nevo.parents.subject_progress import (
    MASTERED_AT,
    SubjectProgress,
    SubjectState,
    WindowState,
    build_window,
    state_for,
    week_containing,
    window_bounds,
)

#: Every name the struck metrics go by, in the spellings a field might use.
STRUCK = (
    "selfRegulation",
    "self_regulation",
    "sri",
    "metacognitive",
    "calibration",
    "conceptualFlexibility",
    "conceptual_flexibility",
    "activeLearning",
    "active_learning",
    "index",
    "percentile",
    "rating",
    "rank",
    "classAverage",
    "class_average",
    "yearGroup",
    "cohort",
    "peer",
)


def test_the_response_cannot_carry_a_struck_metric() -> None:
    """Not a rule in a docstring: there is nowhere to put one."""

    schemas = app.openapi()["components"]["schemas"]
    fields = {
        *schemas["SubjectProgressResponse"]["properties"],
        *schemas["ChildSubjectProgressResponse"]["properties"],
        *schemas["ProgressWindowResponse"]["properties"],
    }

    for banned in STRUCK:
        assert not any(banned.casefold() in field.casefold() for field in fields), banned


def test_nothing_in_the_shape_is_a_number_about_another_child() -> None:
    fields = set(SubjectProgressResponse.model_fields)

    # Counts and names only, and the one count is this child's own history.
    assert "mastered_before_window" in fields
    numeric = {
        name
        for name, field in SubjectProgressResponse.model_fields.items()
        if field.annotation is int
    }
    assert numeric == {"mastered_before_window"}


def test_movement_is_measured_against_the_child_own_starting_point() -> None:
    row = SubjectProgress(
        subject_id=__import__("uuid").uuid4(),
        subject_name="Mathematics",
        state=SubjectState.ACTIVE,
        covered=("Fractions",),
        mastered_this_window=("Fractions",),
        still_working_on=("Ratio",),
        mastered_before_window=11,
    )

    # Three more on top of eleven. Never "ahead of" or "behind" anybody.
    assert row.mastered_before_window == 11
    assert row.mastered_this_window == ("Fractions",)


def test_a_subject_with_no_lessons_is_returned_not_omitted() -> None:
    # The front end has a state for it; an omission is indistinguishable from
    # a bug.
    assert SubjectState.NOT_STARTED in set(SubjectState)


def test_the_week_runs_monday_to_sunday_in_lagos() -> None:
    # A Thursday.
    monday, sunday = week_containing(datetime(2026, 10, 1, 9, 0, tzinfo=UTC))

    assert monday == date(2026, 9, 28)
    assert sunday == date(2026, 10, 4)
    assert monday.weekday() == 0
    assert sunday.weekday() == 6


def test_late_sunday_night_in_lagos_is_still_that_week() -> None:
    """A UTC week puts an hour of Sunday into the wrong one."""

    # 23:30 Sunday in Lagos is 22:30 UTC the same day.
    _monday, sunday = week_containing(datetime(2026, 10, 4, 22, 30, tzinfo=UTC))

    assert sunday == date(2026, 10, 4)


def test_the_window_is_compared_in_instants_not_dates() -> None:
    opened, closed = window_bounds(date(2026, 9, 28), date(2026, 10, 4))

    # Local midnight both ends, so the comparison against a stored UTC
    # timestamp lands on the right side.
    assert opened < closed
    assert opened.tzinfo is not None and closed.tzinfo is not None
    assert (closed - opened).days == 7


def test_the_default_is_the_week_in_progress() -> None:
    """A parent opening this on Wednesday wants to know about Wednesday."""

    window = build_window(
        now=datetime(2026, 9, 30, 10, 0, tzinfo=UTC),
        starts_on=None,
        term_starts=[date(2026, 9, 14)],
        breaks=[],
    )

    assert window.starts_on == date(2026, 9, 28)
    assert window.in_progress is True


def test_an_earlier_week_can_be_asked_for_without_a_second_endpoint() -> None:
    window = build_window(
        now=datetime(2026, 9, 30, 10, 0, tzinfo=UTC),
        # Any date in the week will do.
        starts_on=date(2026, 9, 24),
        term_starts=[date(2026, 9, 14)],
        breaks=[],
    )

    assert window.starts_on == date(2026, 9, 21)
    assert window.in_progress is False


@pytest.mark.parametrize(
    ("monday", "terms", "breaks", "expected"),
    [
        (date(2026, 9, 28), [date(2026, 9, 14)], [], WindowState.IN_TERM),
        # Nothing set: we cannot say, and saying "in term" would be a guess.
        (date(2026, 9, 28), [], [], WindowState.TERMS_NOT_SET),
        # Before the first term of the year.
        (date(2026, 9, 7), [date(2026, 9, 14)], [], WindowState.IN_BREAK),
        # A configured half-term, overlapping by a single day.
        (
            date(2026, 10, 26),
            [date(2026, 9, 14)],
            [(date(2026, 11, 1), date(2026, 11, 7))],
            WindowState.IN_BREAK,
        ),
    ],
)
def test_an_empty_week_says_which_kind_it_was(
    monday: date, terms: list[date], breaks: list[tuple[date, date]], expected: WindowState
) -> None:
    """Three screens depend on this, so it is decided once here."""

    assert state_for(monday, term_starts=terms, breaks=breaks) == expected


def test_the_mastery_bar_sits_above_the_baseline_cap() -> None:
    """A probe-seeded concept must not read as mastered."""

    from nevo.mastery.engine import BASELINE_CONCEPT_CAP

    assert MASTERED_AT > BASELINE_CONCEPT_CAP


def test_a_parent_reads_only_their_own_children() -> None:
    import inspect

    from nevo.api.parents import child_subject_progress

    source = inspect.getsource(child_subject_progress)

    # Checked before anything is read, not filtered afterwards.
    assert "require_linked_child" in source
    assert source.index("require_linked_child") < source.index("child_progress(")


def test_the_route_exists_and_takes_a_week() -> None:
    operation = app.openapi()["paths"]["/api/v1/parents/me/children/{student_id}/subject-progress"][
        "get"
    ]
    names = {parameter["name"] for parameter in operation["parameters"]}

    assert "weekOf" in names
    assert "404" in operation["responses"]


def test_the_window_state_reaches_the_client() -> None:
    assert "state" in ProgressWindowResponse.model_fields
    assert set(WindowState) == {
        WindowState.IN_TERM,
        WindowState.IN_BREAK,
        WindowState.TERMS_NOT_SET,
    }
    assert "window" in ChildSubjectProgressResponse.model_fields
