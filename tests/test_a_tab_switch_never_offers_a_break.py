"""Switching app or tab must not lead to a break offer.

Lydia's ruling, 10 November. The first attempt left focus_drop out of the
figure break offers read - and the app never sends focus_drop. On a tab switch
it sends task_switch, then return_after_pause, and engagement() folds
return_after_pause into the focus penalty whenever any navigation count is
present. So the exclusion removed the one term that was never there, and a tab
switch could still produce an offer about three minutes later.

Yinka caught that on 12 November by reading breaks.py:83 against
runtime_evidence.py. These tests use the indicators the app actually sends.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from nevo.domain.signal_events.vocabulary import SignalEventType as Event
from nevo.intelligence.runtime_evidence import (
    AWAY_INDICATORS,
    engagement,
    engagement_decline_seconds,
)

NOW = datetime(2026, 11, 12, 8, 20, 0, tzinfo=UTC)


def _signal(indicator: str, value: float, seconds_ago: int):
    return SimpleNamespace(
        event_type=Event.ENGAGEMENT_SIGNAL,
        event_data={"indicator": indicator, "value": value},
        timestamp=NOW - timedelta(seconds=seconds_ago),
        session_id="s1",
    )


def _tab_switch_sequence():
    """What the app sends when a child keeps switching away and coming back.

    task_switch then return_after_pause, repeatedly, which is the shape Yinka
    described. The readings stay inside thirty seconds of each other, because
    a longer gap resets the decline window, and steady_progress continues
    throughout - a child who comes back is still working, which is the point.

    return_after_pause only counts when a navigation signal is in the same
    sixty-second window, so the two have to be interleaved rather than one
    burst followed by the other. That subtlety is why the first version of
    this test did not reproduce the fault.
    """
    events = [_signal("steady_progress", 30, second) for second in range(300, 200, -20)]
    for second in range(190, 0, -20):
        events.append(_signal("task_switch", 1, second))
        events.append(_signal("return_after_pause", 60, second - 5))
        events.append(_signal("steady_progress", 30, second - 10))
    return events


def _healthy_baseline() -> float:
    return engagement([_signal("steady_progress", 30, second) for second in range(900, 700, -20)])


def test_the_indicator_set_names_what_the_app_sends() -> None:
    """focus_drop alone was the mistake."""
    assert {"task_switch", "return_after_pause"} <= AWAY_INDICATORS
    assert "focus_drop" in AWAY_INDICATORS
    # Still counted: a child casting about inside the lesson.
    assert "navigation_fragmentation" not in AWAY_INDICATORS
    assert "rapid_guessing" not in AWAY_INDICATORS


def test_a_tab_switch_lowers_the_full_figure() -> None:
    """The adaptation engine should still see it - that is not being removed."""
    events = _tab_switch_sequence()
    full = engagement(events)
    blind = engagement(events, ignore=AWAY_INDICATORS)
    assert full is not None and blind is not None
    assert full < blind, "the full figure no longer notices a tab switch"


def test_a_tab_switch_does_not_lower_the_break_offer_figure() -> None:
    events = _tab_switch_sequence()
    steady_only = [row for row in events if row.event_data["indicator"] == "steady_progress"]
    assert engagement(events, ignore=AWAY_INDICATORS) == engagement(
        steady_only, ignore=AWAY_INDICATORS
    )


def test_three_minutes_away_no_longer_counts_as_a_decline() -> None:
    """The exact shape Yinka described: an offer about three minutes after."""
    events = _tab_switch_sequence()
    baseline = _healthy_baseline()
    counted = engagement_decline_seconds(events, baseline, NOW)
    ignored = engagement_decline_seconds(events, baseline, NOW, ignore=AWAY_INDICATORS)

    assert counted > 0, "the old figure did not actually count the tab switch"
    assert ignored == 0, "a tab switch still reads as disengagement"


def test_genuine_disengagement_still_counts() -> None:
    """Removing the away signals must not switch the threshold off."""
    events = [_signal("steady_progress", 30, second) for second in range(300, 240, -20)]
    events += [_signal("rapid_guessing", 3, second) for second in (200, 160, 120, 80, 40, 10)]
    assert engagement_decline_seconds(events, _healthy_baseline(), NOW, ignore=AWAY_INDICATORS) > 0


def test_navigation_fragmentation_still_counts() -> None:
    events = [_signal("steady_progress", 30, second) for second in range(300, 240, -20)]
    events += [
        _signal("navigation_fragmentation", 2, second) for second in (200, 160, 120, 80, 40, 10)
    ]
    assert engagement_decline_seconds(events, _healthy_baseline(), NOW, ignore=AWAY_INDICATORS) > 0


@pytest.mark.parametrize("ignore", [frozenset(), AWAY_INDICATORS])
def test_no_events_is_not_a_decline(ignore) -> None:
    assert engagement([], ignore=ignore) is None
    assert engagement_decline_seconds([], 0.8, NOW, ignore=ignore) == 0


def test_the_break_figure_is_the_one_breaks_read() -> None:
    from nevo.intelligence import breaks, runtime_evidence

    breaks_source = breaks.__loader__.get_source(breaks.__name__)
    assert "engagement_decline_seconds_excluding_away >= 180" in breaks_source
    assert "engagement_below_baseline_seconds >= 180" not in breaks_source

    evidence = runtime_evidence.__loader__.get_source(runtime_evidence.__name__)
    assert "ignore=AWAY_INDICATORS" in evidence
    # And it is measured against a baseline taken the same way.
    assert "away_blind_baseline" in evidence
