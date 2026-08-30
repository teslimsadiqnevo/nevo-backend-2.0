from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from statistics import fmean


def build_baseline_profile(
    *, session_id: str, features: Iterable[Mapping[str, object]]
) -> tuple[dict[str, object], dict[str, object]]:
    """Reduce device-produced baseline aggregates into bounded engine settings."""
    rows = list(features)
    values: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        for key, value in row.items():
            if isinstance(value, bool):
                values[key.casefold()].append(float(value))
            elif isinstance(value, int | float):
                values[key.casefold()].append(float(value))

    def average(*names: str, default: float) -> float:
        candidates = [item for name in names for item in values.get(name.casefold(), ())]
        return fmean(candidates) if candidates else default

    accuracy = _normalise_ratio(
        average("accuracy", "comprehension_accuracy", "correct_ratio", default=0.65)
    )
    response_ms = max(
        100.0,
        average("response_time_ms", "mean_response_time_ms", "latency_ms", default=2500.0),
    )
    reading_wpm = _clamp(average("reading_wpm", "words_per_minute", default=120.0), 30.0, 350.0)
    attention_minutes = _clamp(
        average("attention_minutes", "sustained_attention_minutes", default=12.0), 1.0, 60.0
    )
    working_memory = round(_clamp(1.0 + accuracy * 4.0, 1.0, 5.0))
    processing_speed = round(_clamp(6.0 - response_ms / 1000.0, 1.0, 5.0))
    confidence = "medium" if len(rows) >= 3 else "low"
    now = datetime.now(UTC).isoformat()

    profile: dict[str, object] = {
        "version": 1,
        "session_id": session_id,
        "feature_count": len(rows),
        "working_memory_capacity": working_memory,
        "processing_speed": processing_speed,
        "reading_wpm": round(reading_wpm, 2),
        "attention_span_minutes": round(attention_minutes, 2),
        "comprehension_accuracy": round(accuracy, 4),
        "confidence": confidence,
        "updated_at": now,
    }
    engine_config: dict[str, object] = {
        "version": 1,
        "reading": {
            "targetWordsPerMinute": round(reading_wpm),
            "segmentWordTarget": round(_clamp(reading_wpm * 1.5, 60, 260)),
        },
        "pacing": {
            "responseTimeTargetMs": round(response_ms),
            "attentionWindowMinutes": round(attention_minutes),
        },
        "support": {
            "initialScaffoldLevel": "partial" if accuracy >= 0.7 else "full",
            "comprehensionCheckInterval": 2 if working_memory <= 2 else 3,
        },
        "generatedFromBaselineAt": now,
    }
    return profile, engine_config


def _normalise_ratio(value: float) -> float:
    return _clamp(value / 100.0 if value > 1.0 else value, 0.0, 1.0)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
