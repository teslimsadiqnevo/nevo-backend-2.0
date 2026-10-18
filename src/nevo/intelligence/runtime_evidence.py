"""Derive live decisions from persisted, permitted events and marked answers."""

import math
from datetime import timedelta
from statistics import mean, median

from nevo.domain.signal_events.vocabulary import SignalEventType as Event


def _number(value):
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        else 0.0
    )


def engagement(events):
    readings = [row for row in events if row.event_type is Event.ENGAGEMENT_SIGNAL]
    if not readings:
        return None
    durations = {"focus_drop": 0.0, "steady_progress": 0.0}
    counts = 0.0
    for row in readings:
        data = row.event_data or {}
        key, value = data.get("indicator"), _number(data.get("value"))
        if key in durations:
            durations[key] += value
        elif key in {"task_switch", "navigation_fragmentation", "rapid_guessing"}:
            counts += value
    total = sum(durations.values())
    if not total and not counts:
        return None
    focus_fraction = durations["focus_drop"] / total if total else 0
    return max(0.0, 1 - focus_fraction - min(0.6, counts * 0.08))


def derive_runtime_evidence(
    *, attempts, events, historical_attempts, historical_events, baseline, current, now, started_at
):
    # Callers pass newest-first marked attempts. Declines/unmarked prose are not misses.
    marked = [item for item in attempts if item.correct is not None]
    recent = marked[:3]
    previous = marked[3:] or [item for item in historical_attempts if item.correct is not None]
    previous_accuracy = (
        mean(float(item.correct) for item in previous)
        if previous
        else baseline.get("comprehension_accuracy")
    )
    score = mean(float(item.correct) for item in recent) if recent else None
    times = [item.response_time_ms for item in recent if item.response_time_ms is not None]
    previous_times = [
        item.response_time_ms for item in previous if item.response_time_ms is not None
    ]
    reference_time = median(previous_times) if previous_times else baseline.get("response_time_ms")
    cutoff = now - timedelta(minutes=3)
    live_events = [event for event in events if cutoff <= event.timestamp <= now]
    earlier_events = [event for event in events if event.timestamp < cutoff]
    engagement_score = engagement(live_events)
    historical_by_session = {}
    for event in historical_events:
        historical_by_session.setdefault(event.session_id, []).append(event)
    personal = [
        value
        for group in historical_by_session.values()
        if (value := engagement(group)) is not None
    ]
    engagement_baseline = mean(personal) if personal else engagement(earlier_events)
    errors = 0
    for item in marked:
        if item.correct:
            break
        errors += 1
    segment_keys = {str(current.id), current.segment_key} if current else set()
    replay_count = sum(
        1
        for event in live_events
        if event.event_type in {Event.REPLAY, Event.NARRATION_REPLAYED}
        and str(event.event_data.get("segmentId")) in segment_keys
    )
    focus_ms = sum(
        _number(event.event_data.get("value"))
        for event in live_events
        if event.event_type is Event.ENGAGEMENT_SIGNAL
        and event.event_data.get("indicator") == "focus_drop"
    )
    below = (
        engagement_score is not None
        and engagement_baseline is not None
        and engagement_score <= engagement_baseline - 0.15
    )
    break_ends = [
        event.timestamp
        for event in events
        if event.event_type is Event.BREAK_END and event.timestamp <= now
    ]
    continuous_start = max([started_at, *break_ends])
    return dict(  # noqa: C408 - named signal fields align with dataclass replacement
        comprehension_score=score * 100 if score is not None else None,
        session_average_comprehension=float(previous_accuracy) * 100
        if previous_accuracy is not None
        else None,
        accuracy_below_baseline=score is not None
        and previous_accuracy is not None
        and score <= float(previous_accuracy) - 0.2,
        response_time_below_baseline=bool(
            times and reference_time and median(times) >= float(reference_time) * 1.5
        ),
        engagement_score=engagement_score,
        engagement_baseline=engagement_baseline,
        engagement_below_baseline_seconds=min(180, int(focus_ms / 1000)) if below else 0,
        consecutive_errors=errors,
        replay_count_on_segment=replay_count,
        continuous_minutes=max(0, (now - continuous_start).total_seconds() / 60),
    )
