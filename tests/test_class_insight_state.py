"""The engine says which of three things a week was, and says it in words.

The console was deciding this from the length of three arrays - a threshold in
the client, against the architecture rule, and live. It also could not tell a
settled week from a new class, so a class having a good week was told insights
were still being gathered.

A quiet week is not a gap in the data. It is the engine having looked and found
nothing needing attention, which is a finding worth telling a teacher.
"""

from __future__ import annotations

import inspect

from nevo.api import insights
from nevo.domain.intelligence.vocabulary import ClassInsightState
from nevo.main import app


def test_the_response_carries_a_state() -> None:
    fields = app.openapi()["components"]["schemas"]["ClassInsightsNarrativeResponse"]["properties"]

    assert "state" in fields


def test_there_are_exactly_three_states() -> None:
    assert [s.value for s in ClassInsightState] == ["summary", "settled", "gathering"]


def test_both_strings_are_always_sent() -> None:
    # The nullable design was withdrawn: null read as a data gap, and a quiet
    # week is the opposite of that.
    fields = app.openapi()["components"]["schemas"]["ClassInsightsNarrativeResponse"]["properties"]

    for name in ("weeklySummary", "lookingAhead"):
        assert "anyOf" not in fields[name], f"{name} became nullable"
        assert fields[name].get("type") == "string"


def test_the_threshold_lives_in_the_engine() -> None:
    assert isinstance(insights.SESSIONS_FOR_A_PATTERN, int)
    assert isinstance(insights.LEARNERS_FOR_A_PATTERN, int)
    # One learner's quiet week says nothing about a class.
    assert insights.LEARNERS_FOR_A_PATTERN >= 2


def test_every_state_has_copy_of_its_own() -> None:
    """Each branch writes both strings; the client renders and decides nothing."""
    source = inspect.getsource(insights.class_insights_narrative)

    for state in ClassInsightState:
        assert f"ClassInsightState.{state.name}" in source, state


def test_a_settled_week_does_not_read_like_an_absent_one() -> None:
    source = inspect.getsource(insights.class_insights_narrative)
    settled = source[source.index("ClassInsightState.SETTLED") :]

    assert "nothing stood out" in settled
    assert "gathering" not in settled.split("return")[0].lower()


def test_the_break_and_feeling_signals_can_be_recorded() -> None:
    """The consolidation break was asking a child how they felt and throwing
    the answer away, because there was no event type to carry it."""
    from nevo.domain.signal_events.vocabulary import SignalEventType

    values = {item.value for item in SignalEventType}

    assert {
        "break_start",
        "break_end",
        "feeling_checkin",
        "module_boundary_reached",
    } <= values


def test_the_postgres_enum_is_migrated_too() -> None:
    # signal_event_type is a native enum, so the Python side alone would let a
    # write through the API and have the database refuse it.
    from pathlib import Path

    migration = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260918_0060_break_and_feeling_signals.py"
    ).read_text()

    for value in ("break_start", "break_end", "feeling_checkin", "module_boundary_reached"):
        assert value in migration
    assert "ADD VALUE IF NOT EXISTS" in migration
