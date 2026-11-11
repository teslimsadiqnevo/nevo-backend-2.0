"""Lydia's break-offer rules, 10 November. The pill only.

She said breaks came too often, and the causes were cheap triggers rather than
a missing rate limit: one wrong answer plus one replay was enough, switching
tab counted as disengagement, declining bought two minutes, and nothing capped
how many a child could be offered in one lesson.

The standing buttons are untouched by any of this.
"""

from __future__ import annotations

import pytest

from nevo.domain.intelligence.vocabulary import BreakSeverity, BreakThreshold, BreakType
from nevo.intelligence.breaks import (
    BETWEEN_OFFERS_SECONDS,
    DECLINE_QUIET_SECONDS,
    MAX_OFFERS_PER_LESSON,
    monitor_break_thresholds,
)
from nevo.intelligence.entities import LearnerProfileSnapshot, RuntimeSignals


def _profile(attention_span: int | None = 20) -> LearnerProfileSnapshot:
    return LearnerProfileSnapshot(attention_span=attention_span)


def _offer(**signals) -> object:
    return monitor_break_thresholds(signals=RuntimeSignals(**signals), profile=_profile())


def _offered(**signals) -> bool:
    return bool(_offer(**signals).triggered_thresholds)


# --- the numbers themselves -------------------------------------------------


def test_the_numbers_are_lydias() -> None:
    assert DECLINE_QUIET_SECONDS == 15 * 60
    assert BETWEEN_OFFERS_SECONDS == 10 * 60
    assert MAX_OFFERS_PER_LESSON == 2


# --- what no longer triggers an offer ---------------------------------------


def test_one_miss_and_one_replay_is_no_longer_enough() -> None:
    """The cheapest old trigger, and the reason they came too often."""
    assert not _offered(consecutive_errors=1, replay_count_on_segment=1)


def test_switching_app_or_tab_does_not_trigger_an_offer() -> None:
    """focus_drop is what the page emits when a child switches away.

    The full engagement figure counts it. Break offers read the figure with
    it excluded, so a child reading something in another tab is not asked to
    take a break.
    """
    assert not _offered(engagement_below_baseline_seconds=600)
    assert not _offered(consecutive_errors=1, engagement_below_baseline_seconds=600)


def test_genuine_engagement_decline_still_triggers_one() -> None:
    """The exclusion must not switch the threshold off altogether."""
    assert _offered(engagement_decline_seconds_excluding_away=190)


# --- frustration, as she defined it -----------------------------------------


def test_three_misses_in_a_row_on_one_concept() -> None:
    result = _offer(consecutive_errors_same_concept=3)
    assert BreakThreshold.FRUSTRATION_HIGH in result.triggered_thresholds


@pytest.mark.parametrize("misses", [1, 2])
def test_fewer_than_three_on_one_concept_is_not_frustration(misses: int) -> None:
    assert not _offered(consecutive_errors_same_concept=misses)


def test_two_misses_on_one_step_with_support_in_between() -> None:
    """A child who has already asked for help and still cannot get past it."""
    result = _offer(consecutive_errors_same_step=2, support_used_between_errors=True)
    assert BreakThreshold.FRUSTRATION_HIGH in result.triggered_thresholds


def test_two_misses_on_one_step_with_nothing_in_between_is_not() -> None:
    assert not _offered(consecutive_errors_same_step=2)


def test_an_explicit_frustration_signal_is_still_honoured() -> None:
    """The app can say so directly; this only changes what we infer."""
    assert _offered(frustration_detected=True)


# --- the rate limits --------------------------------------------------------


def test_declining_buys_fifteen_minutes() -> None:
    assert not _offered(frustration_detected=True, break_declined_seconds_ago=14 * 60)
    assert _offered(frustration_detected=True, break_declined_seconds_ago=15 * 60)


def test_two_minutes_after_a_decline_is_no_longer_enough() -> None:
    """The old window, and the reason "Not now" felt ignored."""
    assert not _offered(frustration_detected=True, break_declined_seconds_ago=121)


def test_ten_minutes_between_offers_even_when_ignored() -> None:
    """Declining was the only thing that held the pill back before."""
    assert not _offered(frustration_detected=True, break_offered_seconds_ago=9 * 60)
    assert _offered(frustration_detected=True, break_offered_seconds_ago=10 * 60)


def test_at_most_two_per_lesson() -> None:
    assert _offered(frustration_detected=True, session_break_count=1)
    assert not _offered(frustration_detected=True, session_break_count=2)


def test_after_the_second_the_pill_does_not_come_back() -> None:
    """However long has passed and however the lesson goes afterwards."""
    for signals in (
        {"frustration_detected": True},
        {"consecutive_errors_same_concept": 9},
        {"continuous_minutes": 240},
        {"engagement_decline_seconds_excluding_away": 999},
    ):
        assert not _offered(session_break_count=5, **signals)


def test_a_break_in_progress_still_suppresses_everything() -> None:
    assert not _offered(frustration_detected=True, break_in_progress=True)


# --- the timer ---------------------------------------------------------------


def test_the_timer_still_offers_a_break() -> None:
    """Read as "the timer firing is a trigger", since the next rule says
    explicitly what no longer triggers one. Flagged to Lydia to confirm."""
    result = _offer(continuous_minutes=25)
    assert BreakThreshold.TIME_THRESHOLD in result.triggered_thresholds


def test_the_timer_is_still_rate_limited_like_everything_else() -> None:
    assert not _offered(continuous_minutes=25, session_break_count=2)
    assert not _offered(continuous_minutes=25, break_declined_seconds_ago=60)


# --- the early, short pause -------------------------------------------------


def test_the_early_short_pause_never_follows_a_single_miss() -> None:
    """Her wording: it comes after several misses, not the first.

    There is no route to a MICRO pause that does not pass through
    frustration or a persistent stall, and both now need two misses at
    least, so a first miss cannot produce one.
    """
    assert _offer(consecutive_errors=1).break_type is None
    assert _offer(consecutive_errors=1, replay_count_on_segment=1).break_type is None


def test_a_short_pause_is_what_several_misses_produce() -> None:
    result = _offer(consecutive_errors_same_concept=3)
    assert result.break_type is BreakType.MICRO
    assert result.severity is not BreakSeverity.NONE


def test_nothing_at_all_offers_nothing() -> None:
    result = _offer()
    assert result.triggered_thresholds == ()
    assert result.break_type is None
    assert result.severity is BreakSeverity.NONE
