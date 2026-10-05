from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from statistics import fmean

from nevo.domain.intelligence.vocabulary import ScaffoldingLevel


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
            # Real ScaffoldingLevel values. This emitted "partial" and
            # "full", which are not in that enum and never have been - so the
            # one setting that says how much help a child starts with could
            # not be read against the ladder it belongs to. Ask B24.
            "initialScaffoldLevel": (
                ScaffoldingLevel.STANDARD.value
                if accuracy >= 0.7
                else ScaffoldingLevel.STRONG.value
            ),
            "comprehensionCheckInterval": 2 if working_memory <= 2 else 3,
        },
        "generatedFromBaselineAt": now,
    }
    return profile, engine_config


def _normalise_ratio(value: float) -> float:
    return _clamp(value / 100.0 if value > 1.0 else value, 0.0, 1.0)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


#: Conditions a baseline trial can belong to. Reported per trial so the
#: breakdown is derived here rather than on the device, which is the whole
#: point of taking trials instead of aggregates. SCRUM-175, ask B9.
TRIAL_CONDITIONS = ("congruent", "incongruent", "dot_ratio", "reading_mode")


def reduce_trials(
    trials: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Turn raw per-trial results into the aggregate features the engine wants.

    The device was doing this: it marked each trial against an answer key it
    held, averaged the results and sent a vector. That put a measure of a
    child in the client's hands, and the architecture forbids it - so the
    trials arrive as they happened and the arithmetic is done here.

    One feature row per dimension, plus one per condition where trials carry
    one, which is what makes a congruency or dot-ratio breakdown possible at
    all. Trials themselves are not kept: the reduction is what the engine
    reads, and holding sixty raw trials per child earns nothing.
    """

    from collections import defaultdict

    buckets: dict[tuple[str, str | None], list[Mapping[str, object]]] = defaultdict(list)
    for trial in trials:
        dimension = str(trial.get("dimension") or "unknown").casefold()
        condition = trial.get("condition")
        buckets[(dimension, str(condition).casefold() if condition else None)].append(trial)

    features: list[dict[str, object]] = []
    for (dimension, condition), rows in sorted(
        buckets.items(), key=lambda item: (item[0][0], item[0][1] or "")
    ):
        correct = [bool(row.get("correct")) for row in rows]
        times = [
            float(value)
            for row in rows
            if isinstance(value := row.get("responseTimeMs"), int | float)
        ]
        feature: dict[str, object] = {
            "dimension": dimension,
            f"{dimension}_accuracy": (sum(correct) / len(correct)) if correct else 0.0,
            f"{dimension}_trials": len(rows),
        }
        if times:
            ordered = sorted(times)
            middle = len(ordered) // 2
            feature[f"{dimension}_mean_response_ms"] = sum(times) / len(times)
            # The median as well as the mean: one slow trial from a child who
            # looked away drags a mean of twenty and says nothing true.
            feature[f"{dimension}_median_response_ms"] = (
                ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
            )
        if condition:
            feature["condition"] = condition
            feature[f"{dimension}_{condition}_accuracy"] = feature[f"{dimension}_accuracy"]
        features.append(feature)
    return features
