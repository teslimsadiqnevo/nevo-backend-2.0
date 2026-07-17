from nevo.domain.intelligence.vocabulary import BreakType
from nevo.intelligence.adaptation import balanced_profile
from nevo.intelligence.breaks import monitor_break_thresholds
from nevo.intelligence.entities import RuntimeSignals


def test_monitor_break_thresholds_selects_micro_for_mild_signal() -> None:
    result = monitor_break_thresholds(
        signals=RuntimeSignals(replay_count_on_segment=3),
        profile=balanced_profile(),
    )

    assert result.triggered_thresholds == ("replay_accumulation",)
    assert result.severity == "mild"
    assert result.break_type is BreakType.MICRO


def test_monitor_break_thresholds_selects_movement_for_sedentary_decline() -> None:
    result = monitor_break_thresholds(
        signals=RuntimeSignals(
            continuous_minutes=22,
            engagement_below_baseline_seconds=190,
        ),
        profile=balanced_profile(),
    )

    assert result.break_type is BreakType.MOVEMENT
    assert set(result.triggered_thresholds) == {
        "time_threshold",
        "engagement_decline",
    }


def test_monitor_break_thresholds_selects_consolidation_mid_session() -> None:
    result = monitor_break_thresholds(
        signals=RuntimeSignals(
            comprehension_score=55,
            session_average_comprehension=80,
            midpoint_reached=True,
        ),
        profile=balanced_profile(),
    )

    assert result.break_type is BreakType.CONSOLIDATION


def test_monitor_break_thresholds_selects_full_for_multiple_high_severity() -> None:
    result = monitor_break_thresholds(
        signals=RuntimeSignals(
            engagement_below_baseline_seconds=200,
            comprehension_score=40,
            session_average_comprehension=70,
            consecutive_errors=3,
        ),
        profile=balanced_profile(),
    )

    assert result.severity == "high"
    assert result.break_type is BreakType.FULL
