"""Verified away intervals, scoped to one lesson sitting and section."""

from datetime import UTC, datetime, timedelta


def attention_state(sitting) -> dict:
    return dict((sitting.delivery_state or {}).get("attention") or {})


def active_response_ms(
    sitting, reported_ms: int | None, *, at: datetime, segment_id: str | None
) -> int | None:
    if reported_ms is None:
        return None
    attention = attention_state(sitting)
    if attention.get("open"):
        return None
    start = at - timedelta(milliseconds=reported_ms)
    try:
        observed_at = datetime.fromisoformat(attention["observedAt"])
    except (KeyError, TypeError, ValueError):
        return None
    if observed_at.tzinfo is None or start < observed_at:
        return None
    if attention.get("historyTruncatedAt"):
        try:
            if start < datetime.fromisoformat(attention["historyTruncatedAt"]):
                return None
        except (TypeError, ValueError):
            return None
    away_ms = 0
    for interval in attention.get("intervals") or []:
        if segment_id and interval.get("segmentId") != segment_id:
            continue
        try:
            away_at = datetime.fromisoformat(interval["awayAt"])
            returned_at = datetime.fromisoformat(interval["returnedAt"])
        except (KeyError, TypeError, ValueError):
            continue
        if away_at.tzinfo is None or returned_at.tzinfo is None:
            continue
        overlap = max(timedelta(0), min(returned_at, at) - max(away_at, start))
        away_ms += int(overlap.total_seconds() * 1000)
    return max(0, reported_ms - away_ms)


def transition(
    sitting,
    *,
    action: str,
    segment_id: str,
    client_event_id: str | None = None,
    at: datetime | None = None,
    client_away_duration_ms: int | None = None,
) -> dict:
    now = at or datetime.now(UTC)
    delivery = dict(sitting.delivery_state or {})
    attention = dict(delivery.get("attention") or {})
    seen = list(attention.get("seenEventIds") or [])
    if client_event_id and client_event_id in seen:
        return attention
    open_interval = attention.get("open")
    if action == "away":
        if open_interval is None:
            open_interval = {"segmentId": segment_id, "awayAt": now.isoformat()}
            attention["open"] = open_interval
    elif action == "return" and open_interval is not None:
        if open_interval.get("segmentId") != segment_id:
            return attention
        if client_away_duration_ms is not None:
            measured_start = now - timedelta(milliseconds=client_away_duration_ms)
            if measured_start < sitting.started_at:
                measured_start = sitting.started_at
            open_interval = {
                **open_interval,
                "awayAt": measured_start.isoformat(),
                "timingSource": "client_elapsed_duration",
            }
        closed = {**open_interval, "returnedAt": now.isoformat()}
        intervals = [*(attention.get("intervals") or []), closed]
        if len(intervals) > 200:
            attention["historyTruncatedAt"] = intervals[-200]["awayAt"]
        attention["intervals"] = intervals[-200:]
        attention["open"] = None
        attention.setdefault("observedAt", now.isoformat())
    elif action == "return":
        attention.setdefault("observedAt", now.isoformat())
    if client_event_id:
        attention["seenEventIds"] = [*seen, client_event_id][-200:]
    delivery["attention"] = attention
    sitting.delivery_state = delivery
    return attention
