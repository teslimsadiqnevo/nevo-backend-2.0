from nevo.domain.intelligence.vocabulary import BreakSeverity, BreakThreshold, BreakType
from nevo.intelligence.entities import (
    BreakThresholdResult,
    LearnerProfileSnapshot,
    RuntimeSignals,
)


def monitor_break_thresholds(
    *,
    signals: RuntimeSignals,
    profile: LearnerProfileSnapshot,
) -> BreakThresholdResult:
    thresholds: list[BreakThreshold] = []
    if signals.continuous_minutes >= 20:
        thresholds.append(BreakThreshold.TIME_THRESHOLD)
    if signals.engagement_below_baseline_seconds >= 180:
        thresholds.append(BreakThreshold.ENGAGEMENT_DECLINE)
    if _comprehension_drop(signals):
        thresholds.append(BreakThreshold.COMPREHENSION_DROP)
    if signals.consecutive_errors >= 3:
        thresholds.append(BreakThreshold.REPEATED_ERRORS)
    if signals.replay_count_on_segment >= 3:
        thresholds.append(BreakThreshold.REPLAY_ACCUMULATION)

    if not thresholds:
        return BreakThresholdResult(
            triggered_thresholds=(),
            severity=BreakSeverity.NONE,
            break_type=None,
            reason=None,
        )

    break_type = select_break_type(
        triggered_thresholds=tuple(thresholds),
        signals=signals,
        profile=profile,
    )
    severity = _severity(thresholds)
    return BreakThresholdResult(
        triggered_thresholds=tuple(thresholds),
        severity=severity,
        break_type=break_type,
        reason=_reason_for(break_type, thresholds),
    )


def select_break_type(
    *,
    triggered_thresholds: tuple[str, ...],
    signals: RuntimeSignals,
    profile: LearnerProfileSnapshot,
) -> BreakType:
    high_severity = {
        "engagement_decline",
        "comprehension_drop",
        "repeated_errors",
    }
    if (
        len(triggered_thresholds) >= 3
        or len(set(triggered_thresholds).intersection(high_severity)) >= 2
    ):
        return BreakType.FULL

    if "time_threshold" in triggered_thresholds and "engagement_decline" in triggered_thresholds:
        return BreakType.MOVEMENT

    if signals.midpoint_reached and {"comprehension_drop", "replay_accumulation"}.intersection(
        triggered_thresholds
    ):
        return BreakType.CONSOLIDATION

    if (
        profile.working_memory_capacity is not None
        and profile.working_memory_capacity <= 2
        and {"repeated_errors", "comprehension_drop"}.intersection(triggered_thresholds)
    ):
        return BreakType.CONSOLIDATION

    if "time_threshold" in triggered_thresholds:
        return BreakType.MOVEMENT

    return BreakType.MICRO


def _comprehension_drop(signals: RuntimeSignals) -> bool:
    if signals.comprehension_score is None or signals.session_average_comprehension is None:
        return False
    return signals.session_average_comprehension - signals.comprehension_score >= 20


def _severity(thresholds: list[BreakThreshold]) -> BreakSeverity:
    if len(thresholds) >= 3:
        return BreakSeverity.HIGH
    if len(thresholds) == 2:
        return BreakSeverity.MEDIUM
    return BreakSeverity.MILD


def _reason_for(break_type: BreakType, thresholds: list[BreakThreshold]) -> str:
    joined = ", ".join(threshold.value for threshold in thresholds)
    if break_type is BreakType.FULL:
        return f"Multiple high-severity signals fired: {joined}."
    if break_type is BreakType.MOVEMENT:
        return f"Extended continuous work or attention decline detected: {joined}."
    if break_type is BreakType.CONSOLIDATION:
        return f"Memory or comprehension support signal detected: {joined}."
    return f"Mild learning support signal detected: {joined}."
