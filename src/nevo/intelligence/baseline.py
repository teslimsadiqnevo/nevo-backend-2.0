from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from math import isfinite
from statistics import fmean

from nevo.domain.intelligence.vocabulary import ScaffoldingLevel


def build_baseline_profile(
    *,
    session_id: str,
    features: Iterable[Mapping[str, object]],
    previous_profile: Mapping[str, object] | None = None,
    previous_engine_config: Mapping[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Reduce device-produced baseline aggregates into bounded engine settings."""
    rows = list(features)
    interference_rows = [row for row in rows if row.get("dimension") in {"inhibition", "interference_control"}]
    # This measure must not leak into generic accuracy/processing-speed averages.
    rows = [row for row in rows if row.get("dimension") not in {"inhibition", "interference_control"}]
    values: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        for key, value in row.items():
            if isinstance(value, bool):
                values[key.casefold()].append(float(value))
            elif isinstance(value, int | float) and isfinite(value):
                values[key.casefold()].append(float(value))

    def average(*names: str, default: float) -> float:
        candidates = [item for name in names for item in values.get(name.casefold(), ())]
        return fmean(candidates) if candidates else default

    accuracy = _normalise_ratio(
        average(
            "accuracy", "comprehension_accuracy", "correct_ratio", "domain_accuracy", default=0.65
        )
    )
    response_ms = max(
        100.0,
        average(
            "response_time_ms",
            "mean_response_time_ms",
            "latency_ms",
            "ps_median_response_ms",
            default=2500.0,
        ),
    )
    reading_wpm = _clamp(average("reading_wpm", "words_per_minute", default=120.0), 30.0, 350.0)
    attention_minutes = _clamp(
        average("attention_minutes", "sustained_attention_minutes", default=12.0), 1.0, 60.0
    )
    working_memory = round(_clamp(1.0 + average("wmc_accuracy", default=accuracy) * 4.0, 1.0, 5.0))
    processing_speed = round(_clamp(6.0 - response_ms / 1000.0, 1.0, 5.0))
    confidence = "medium" if len(rows) >= 3 else "low"
    measurements = dict((previous_profile or {}).get("measurements") or {})
    if interference_rows:
        measurements["inhibition"] = interference_rows[-1]["measurement"]
        measurements.pop("interference_control", None)
    for dimension in ("wmc", "ps", "reading", "ans", "attention", "domain"):
        observed = [
            row
            for row in rows
            if row.get("dimension") == dimension and float(row.get(f"{dimension}_trials") or 0) > 0
        ]
        if not observed:
            continue
        count = sum(int(row[f"{dimension}_trials"]) for row in observed)
        measurements[dimension] = {
            "trial_count": count,
            "accuracy": sum(
                float(row.get(f"{dimension}_accuracy") or 0) * int(row[f"{dimension}_trials"])
                for row in observed
            )
            / count,
            "source": "reduced_task_results",
            "calibration": "provisional",
        }
        if dimension == "ans":
            ratios = [
                float(row["ans_mean_dot_ratio"])
                for row in observed
                if row.get("ans_mean_dot_ratio")
            ]
            if ratios:
                measurements[dimension]["mean_dot_ratio"] = fmean(ratios)
    spans = [float(row["wmc_successful_span"]) for row in rows if row.get("wmc_successful_span")]
    if spans:
        measurements["wmc"]["successful_span"] = max(spans)
        working_memory = round(_clamp(max(spans), 1, 5))
    attention_rows = [row for row in rows if row.get("dimension") == "attention"]
    conditions = {str(row.get("condition")): row for row in attention_rows}
    congruent = conditions.get("congruent", {}).get("attention_median_response_ms")
    incongruent = conditions.get("incongruent", {}).get("attention_median_response_ms")
    if "attention" in measurements and attention_rows:
        interference = (
            max(0, (float(incongruent) - float(congruent)) / max(1, float(congruent)))
            if congruent and incongruent
            else None
        )
        measurements["attention"]["interference_ratio"] = interference
        # This is a conservative delivery window, not a measured attention span.
        attention_minutes = _clamp(
            8 + 10 * measurements["attention"]["accuracy"] - 4 * min(1, interference or 0), 5, 20
        )
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
        "response_time_ms": round(response_ms),
        "confidence": confidence,
        "measurements": measurements,
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
    if "ans" in measurements:
        engine_config["support"]["numericalVisuals"] = (
            measurements["ans"]["trial_count"] >= 3 and measurements["ans"]["accuracy"] < 0.7
        )
    measured_reading = bool(values.get("reading_wpm") or values.get("words_per_minute"))
    if not measured_reading:
        profile.pop("reading_wpm", None)
    else:
        profile["reading_wpm_source"] = "measured"
    # Recalibration updates only what this run measured, not default values
    # for unrelated dimensions. A new account still gets safe delivery defaults.
    previous = dict(previous_profile or {})
    if previous:
        dimensions = {str(row.get("dimension", "")) for row in rows}
        modules = {str(row.get("module", "")) for row in rows}
        fields = {
            "working_memory_capacity": "wmc" in dimensions
            or "grid_span" in modules
            or bool(values.get("wmc_accuracy")),
            "processing_speed": any(
                key in values
                for key in (
                    "response_time_ms",
                    "mean_response_time_ms",
                    "latency_ms",
                    "ps_median_response_ms",
                )
            ),
            "attention_span_minutes": "attention" in dimensions
            or bool(values.get("attention_minutes")),
            "comprehension_accuracy": "domain" in dimensions
            or any(
                key in values for key in ("accuracy", "comprehension_accuracy", "domain_accuracy")
            ),
            "reading_wpm": measured_reading,
            "response_time_ms": any(
                key in values
                for key in (
                    "response_time_ms",
                    "mean_response_time_ms",
                    "latency_ms",
                    "ps_median_response_ms",
                )
            ),
        }
        profile = {
            **previous,
            **{key: value for key, value in profile.items() if key not in fields or fields[key]},
        }
        held = dict(previous_engine_config or {})
        for section in ("reading", "pacing", "support"):
            engine_config[section] = {
                **dict(held.get(section) or {}),
                **dict(engine_config[section]),
            }
        if not measured_reading:
            engine_config["reading"] = dict(held.get("reading") or engine_config["reading"])
            if not held.get("reading") and previous.get("reading_wpm"):
                rate = float(previous["reading_wpm"])
                engine_config["reading"].update(
                    targetWordsPerMinute=round(rate),
                    segmentWordTarget=round(_clamp(rate * 1.5, 60, 260)),
                )
        pacing = engine_config["pacing"]
        held_pacing = dict(held.get("pacing") or {})
        if not fields["processing_speed"]:
            pacing["responseTimeTargetMs"] = held_pacing.get(
                "responseTimeTargetMs", previous.get("response_time_ms", response_ms)
            )
        if not fields["attention_span_minutes"]:
            pacing["attentionWindowMinutes"] = held_pacing.get(
                "attentionWindowMinutes", previous.get("attention_span_minutes", attention_minutes)
            )
        if not fields["working_memory_capacity"] and not fields["comprehension_accuracy"]:
            engine_config["support"] = dict(held.get("support") or engine_config["support"])
        else:
            memory = int(profile.get("working_memory_capacity", working_memory))
            accuracy = float(profile.get("comprehension_accuracy", accuracy))
            engine_config["support"].update(
                initialScaffoldLevel=ScaffoldingLevel.STRONG.value
                if memory <= 2 or accuracy < 0.7
                else ScaffoldingLevel.STANDARD.value,
                comprehensionCheckInterval=2 if memory <= 2 else 3,
            )
        if "ans" in dimensions and "ans" in measurements:
            engine_config["support"]["numericalVisuals"] = (
                measurements["ans"]["trial_count"] >= 3 and measurements["ans"]["accuracy"] < 0.7
            )
    interference = measurements.get("inhibition") or measurements.get("interference_control", {})
    if interference.get("status") == "established":
        if interference["accuracyCost"] >= 0.15 and interference["relativeLatencyCost"] >= 0.2:
            engine_config["support"]["shorterTextBlocks"] = True
            engine_config["support"]["simplifiedLayout"] = True
            engine_config["reading"]["segmentWordTarget"] = min(
                100, engine_config["reading"].get("segmentWordTarget", 100)
            )
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

    trials = list(trials)
    interference_trials = [row for row in trials if row.get("dimension") in {"inhibition", "interference_control"}]
    buckets: dict[tuple[str, str | None], list[Mapping[str, object]]] = defaultdict(list)
    for trial in trials:
        if trial.get("dimension") in {"inhibition", "interference_control"}:
            continue
        if (
            trial.get("skipped")
            or trial.get("correct") is None
            or str(trial.get("response") or "").strip().casefold() == "not_sure"
        ):
            continue
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
            and not isinstance(value, bool)
            and isfinite(value)
            and value >= 0
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
        if dimension == "reading":
            measured = [
                float(row["readingWordCount"]) * 60_000 / float(row["responseTimeMs"])
                for row in rows
                if isinstance(row.get("readingWordCount"), (int, float))
                and isinstance(row.get("responseTimeMs"), (int, float))
                and float(row["readingWordCount"]) > 0
                and float(row["responseTimeMs"]) > 0
            ]
            if measured:
                feature["reading_wpm"] = sum(measured) / len(measured)
        if dimension == "wmc":
            spans = [
                float(row["sequenceLength"])
                for row in rows
                if row.get("correct") is True and row.get("sequenceLength")
            ]
            if spans:
                feature["wmc_successful_span"] = max(spans)
        if dimension == "ans":
            ratios = [float(row["dotRatio"]) for row in rows if row.get("dotRatio")]
            if ratios:
                feature["ans_mean_dot_ratio"] = fmean(ratios)
        if condition:
            feature["condition"] = condition
            feature[f"{dimension}_{condition}_accuracy"] = feature[f"{dimension}_accuracy"]
        features.append(feature)
    if interference_trials:
        from nevo.intelligence.interference import reduce_interference

        features.append(
            {
                "dimension": "inhibition",
                "measurement": reduce_interference(interference_trials),
            }
        )
    return features
