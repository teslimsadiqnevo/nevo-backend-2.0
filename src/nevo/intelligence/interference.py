"""Provisional within-child interference contrasts, never a diagnostic score."""

from math import isfinite
from statistics import mean, median

MIN_VALID_PER_CONDITION = 12
ANTICIPATION_FLOOR_MS = 200
SLOW_TAIL_CAP_MS = 5000
CONGRUENT_ACCURACY_GATE = 0.75
POLICY = "binary-word-conflict-provisional-v1"


def reduce_interference(trials):
    buckets = {"congruent": [], "incongruent": []}
    discarded = 0
    for row in trials:
        condition, time = row.get("condition"), row.get("responseTimeMs")
        if (
            condition not in buckets
            or row.get("skipped")
            or row.get("correct") is None
            or not isinstance(time, (int, float))
            or isinstance(time, bool)
            or not isfinite(time)
            or time < ANTICIPATION_FLOOR_MS
        ):
            discarded += 1
            continue
        buckets[condition].append((bool(row["correct"]), min(time, SLOW_TAIL_CAP_MS)))
    result = {
        "status": "unestablished",
        "policy": POLICY,
        "calibration": "provisional",
        "validTrials": {name: len(rows) for name, rows in buckets.items()},
        "discardedTrials": discarded,
    }
    if any(len(rows) < MIN_VALID_PER_CONDITION for rows in buckets.values()):
        return {**result, "reason": "insufficient_valid_trials"}
    accuracy = {name: mean(correct for correct, _ in rows) for name, rows in buckets.items()}
    if accuracy["congruent"] <= CONGRUENT_ACCURACY_GATE:
        return {**result, "reason": "congruent_instructions_unestablished"}
    correct_times = {
        name: [time for correct, time in rows if correct] for name, rows in buckets.items()
    }
    if any(len(times) < 3 for times in correct_times.values()):
        return {**result, "reason": "insufficient_correct_latency_trials"}
    baseline = median(correct_times["congruent"])
    return {
        **result,
        "status": "established",
        "accuracyCost": accuracy["congruent"] - accuracy["incongruent"],
        "relativeLatencyCost": (median(correct_times["incongruent"]) - baseline) / baseline,
    }
