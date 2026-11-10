"""A return is dated when the child came back, not when the request arrived.

Two things the app measured and the server could not use.

A first return after a reload waits 8 to 12 seconds for the sitting id, so
dating it by arrival credited the child with being away for that wait.
clientVisibleForMs says how long the page had been visible when the return was
sent, and arrival minus that is when they came back.

And a device clock can stop while the screen is locked, so the device's own
away figure can only come out short. Short is the direction that hurts: away
time is subtracted from how long an answer took, so undercounting it makes a
child look slower than they were. The server keeps whichever of the two
intervals is longer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from nevo.intelligence.away_time import transition


class Sitting:
    def __init__(self, started_at: datetime) -> None:
        self.started_at = started_at
        self.delivery_state: dict = {}


SEGMENT = "11111111-1111-1111-1111-111111111111"
START = datetime(2026, 11, 10, 16, 0, 0, tzinfo=UTC)


def _away_and_return(**kwargs) -> dict:
    sitting = Sitting(START)
    transition(sitting, action="away", segment_id=SEGMENT, at=START + timedelta(seconds=10))
    transition(sitting, action="return", segment_id=SEGMENT, **kwargs)
    return sitting.delivery_state["attention"]["intervals"][-1]


def _seconds(interval: dict) -> float:
    away = datetime.fromisoformat(interval["awayAt"])
    back = datetime.fromisoformat(interval["returnedAt"])
    return (back - away).total_seconds()


def test_without_the_new_field_nothing_changes() -> None:
    interval = _away_and_return(at=START + timedelta(seconds=40))
    assert _seconds(interval) == 30


def test_the_wait_for_a_sitting_id_is_not_counted_as_away() -> None:
    """The return arrived 12 s after the child was already back and looking."""
    interval = _away_and_return(at=START + timedelta(seconds=52), client_visible_for_ms=12_000)
    # Away from 00:10 to 00:40, not to 00:52.
    assert _seconds(interval) == 30
    assert interval["returnedAt"] == (START + timedelta(seconds=40)).isoformat()


def test_a_visible_time_longer_than_the_sitting_is_clamped_to_its_start() -> None:
    interval = _away_and_return(at=START + timedelta(seconds=52), client_visible_for_ms=600_000)
    assert datetime.fromisoformat(interval["returnedAt"]) == START


def test_the_device_figure_is_used_when_it_is_the_longer_one() -> None:
    """A locked screen whose clock kept running: the device knows best."""
    interval = _away_and_return(at=START + timedelta(seconds=40), client_away_duration_ms=25_000)
    assert interval["timingSource"] == "client_elapsed_duration"
    assert _seconds(interval) == 25


def test_a_sleeping_device_clock_is_recorded_rather_than_silently_trusted() -> None:
    """The clock stopped, so the device reports 3 s for a 30 s gap.

    Nothing in this process can tell a slept clock from a child who came
    straight back, so the disagreement is written down instead of guessed at.
    A run of these on one device is the signal.
    """
    interval = _away_and_return(at=START + timedelta(seconds=40), client_away_duration_ms=3_000)
    assert interval["timingSource"] == "client_elapsed_duration"
    disagreement = interval["clientTimingDisagreement"]
    assert disagreement["clientReportedAwayMs"] == 3_000
    assert disagreement["arrivalIntervalMs"] == 30_000
    assert disagreement["shortfallMs"] == 27_000


def test_an_ordinary_latency_shortfall_is_not_flagged() -> None:
    """Otherwise every return carries a disagreement and none of them mean anything."""
    interval = _away_and_return(at=START + timedelta(seconds=40), client_away_duration_ms=28_000)
    assert "clientTimingDisagreement" not in interval


def test_both_fields_together_behave() -> None:
    """A reload and a device-measured away, which is the real case."""
    interval = _away_and_return(
        at=START + timedelta(seconds=52),
        client_away_duration_ms=25_000,
        client_visible_for_ms=12_000,
    )
    # Back at 00:40; device says 25 s away, so away from 00:15.
    assert interval["returnedAt"] == (START + timedelta(seconds=40)).isoformat()
    assert _seconds(interval) == 25
    assert interval["timingSource"] == "client_elapsed_duration"


def test_an_away_is_never_negative_whatever_the_device_claims() -> None:
    interval = _away_and_return(at=START + timedelta(seconds=40), client_away_duration_ms=0)
    assert _seconds(interval) >= 0


@pytest.mark.parametrize("field", ["clientAwayDurationMs", "clientVisibleForMs"])
def test_both_fields_are_bounded_and_optional_on_the_wire(field: str) -> None:
    from nevo.api.application_attention import AttentionTransition

    name = {
        "clientAwayDurationMs": "client_away_duration_ms",
        "clientVisibleForMs": "client_visible_for_ms",
    }[field]
    spec = AttentionTransition.model_fields[name]
    assert spec.alias == field
    assert spec.default is None
    bounds = str(spec.metadata)
    assert "36000000" in bounds.replace("_", ""), "the 10 hour bound is gone"


def test_neither_field_is_accepted_on_an_away() -> None:
    from nevo.api import application_attention

    source = application_attention.__loader__.get_source(application_attention.__name__)
    assert "away_duration_requires_return" in source
    assert "visible_for_requires_return" in source
