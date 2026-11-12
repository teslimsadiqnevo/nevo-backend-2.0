from nevo.domain.intelligence.vocabulary import BreakSeverity, BreakThreshold, BreakType
from nevo.intelligence.entities import (
    BreakThresholdResult,
    LearnerProfileSnapshot,
    RuntimeSignals,
)

#: Lydia's numbers, 10 November. The pill only; the standing buttons are
#: unaffected by any of this.
#:
#: She said breaks came too often, and the reasons were cheap triggers rather
#: than a missing rate limit: one wrong answer plus one replay was enough, a
#: tab switch counted as disengagement, declining bought two minutes, and
#: nothing capped how many a child could be offered in one lesson.

#: "Not now" lasts fifteen minutes. Was two.
DECLINE_QUIET_SECONDS = 15 * 60

#: At least ten minutes between offers, declined or simply ignored.
BETWEEN_OFFERS_SECONDS = 10 * 60

#: At most two per lesson. After the second the pill does not come back.
MAX_OFFERS_PER_LESSON = 2

#: Three misses in a row on one concept.
FRUSTRATION_ERRORS_SAME_CONCEPT = 3

#: Or two on one step, with a replay or a Slower in between.
FRUSTRATION_ERRORS_SAME_STEP = 2

#: An early, short pause comes after several misses, not the first.
EARLY_PAUSE_MIN_ERRORS = 2


def _offer_is_quiet(signals: RuntimeSignals) -> bool:
    """Whether the pill is being held back regardless of what the child did."""
    if signals.break_in_progress:
        return True
    if signals.session_break_count >= MAX_OFFERS_PER_LESSON:
        return True
    declined = signals.break_declined_seconds_ago
    if declined is not None and declined < DECLINE_QUIET_SECONDS:
        return True
    offered = signals.break_offered_seconds_ago
    return offered is not None and offered < BETWEEN_OFFERS_SECONDS


def _frustrated(signals: RuntimeSignals) -> bool:
    """Lydia's definition, which is narrower than one miss and a replay.

    Either three misses in a row on the same concept, or two on the same step
    with a replay or a Slower in between - the second being a child who has
    already asked for help and still cannot get past it.
    """
    if signals.frustration_detected:
        return True
    if signals.consecutive_errors_same_concept >= FRUSTRATION_ERRORS_SAME_CONCEPT:
        return True
    return (
        signals.consecutive_errors_same_step >= FRUSTRATION_ERRORS_SAME_STEP
        and signals.support_used_between_errors
    )


def monitor_break_thresholds(
    *,
    signals: RuntimeSignals,
    profile: LearnerProfileSnapshot,
) -> BreakThresholdResult:
    if _offer_is_quiet(signals):
        return BreakThresholdResult((), BreakSeverity.NONE, None, None)
    thresholds: list[BreakThreshold] = []
    if _frustrated(signals):
        thresholds.append(BreakThreshold.FRUSTRATION_HIGH)
    if signals.session_adaptation_count >= 2 and signals.consecutive_errors >= 2:
        thresholds.append(BreakThreshold.PERSISTENT_STALL)
    attention_window = min(20, max(5, profile.attention_span or 20))
    if signals.continuous_minutes >= attention_window:
        thresholds.append(BreakThreshold.TIME_THRESHOLD)
    # Switching app or tab no longer counts. The full figure includes
    # focus_drop events, which is what the page emits when a child switches
    # away; the adaptation engine still reads that one.
    if signals.engagement_decline_seconds_excluding_away >= 180:
        thresholds.append(BreakThreshold.ENGAGEMENT_DECLINE)
    # A comprehension drop needs several misses too.
    #
    # Chidi was offered "let's go back over what you just did" at 08:17:55 on
    # 12 November, straight after one miss and its retry. This is the route
    # that did it: the score after a miss sits more than twenty points under
    # the session average, which is still high from before it, so one miss
    # clears the bar on its own. With the midpoint passed that becomes a
    # consolidation break.
    #
    # Lydia's rule was that a pause comes after several misses and not the
    # first. That was applied to the frustration and stall routes; this one
    # is a different break type reached a different way and went round it.
    # Her intent is the same either way, so the same floor applies.
    if _comprehension_drop(signals) and signals.consecutive_errors >= EARLY_PAUSE_MIN_ERRORS:
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
    if {BreakThreshold.FRUSTRATION_HIGH, BreakThreshold.PERSISTENT_STALL}.intersection(
        triggered_thresholds
    ):
        if signals.session_break_count >= 2 or signals.reteaching_exhausted:
            return BreakType.STOP_FOR_DAY
        if signals.session_break_count >= 1 or signals.consecutive_errors >= 3:
            return BreakType.FULL
        # The early, short pause. It cannot reach a first miss: the only
        # route here is FRUSTRATION_HIGH or PERSISTENT_STALL, and both now
        # need at least two misses - three on one concept, or two on one
        # step with support in between. Asserted in the tests rather than
        # re-checked here, because there is no "no break" break type and
        # inventing one would change what the whole function returns.
        return BreakType.MICRO
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
