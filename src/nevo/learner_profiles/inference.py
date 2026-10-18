from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from nevo.domain.learner_profiles.vocabulary import ConfidenceLevel
from nevo.domain.signal_events.vocabulary import SignalEventType
from nevo.learner_profiles.entities import DimensionInference, ObservedActivity
from nevo.signal_events.entities import SignalEventDraft


@dataclass(frozen=True, slots=True)
class _Evidence:
    value: int
    session_id: UUID | None
    note: str


class LearnerProfileInferenceEngine:
    """Infer functional support needs, never a preferred learning modality."""

    def seed_from_observed_sequence(
        self, activities: Iterable[ObservedActivity]
    ) -> dict[str, DimensionInference]:
        evidence: dict[str, list[_Evidence]] = defaultdict(list)
        timing_votes = []
        for activity in activities:
            metrics = activity.metrics
            if activity.activity_number in {1, 2, 4}:
                key = (
                    "response_time_ratio"
                    if activity.activity_number == 2
                    else "completion_time_ratio"
                )
                ratio = self._number(metrics, key, 1.0)
                if ratio <= 0.85:
                    timing_votes.append(4)
                elif ratio >= 1.2:
                    timing_votes.append(2)
            if activity.activity_number == 3:
                first = self._number(metrics, "first_half_consistency", 0)
                second = self._number(metrics, "second_half_consistency", first)
                if first - second >= 0.25:
                    evidence["attention_span"].append(
                        _Evidence(2, None, "within-task consistency decay observed")
                    )
            if activity.activity_number == 4:
                pairs = self._number(metrics, "max_successful_pairs", 0)
                drop = self._number(metrics, "accuracy_curve_drop", 0)
                capacity = (
                    5
                    if pairs >= 7 and drop <= 0.2
                    else 4
                    if pairs >= 5 and drop <= 0.35
                    else 3
                    if pairs >= 3
                    else 2
                )
                evidence["working_memory_capacity"].append(
                    _Evidence(capacity, None, "matching-task completion pattern")
                )
                evidence["cognitive_load_threshold"].append(
                    _Evidence(
                        4 if pairs >= 6 and drop <= 0.25 else 2, None, "cold-start support seed"
                    )
                )
        for value in (4, 2):
            if timing_votes.count(value) >= 2:
                evidence["processing_speed"].append(
                    _Evidence(value, None, "timing pattern across multiple activities")
                )
                break
        return self._results(evidence)

    def infer_from_signal_events(
        self, events: Iterable[SignalEventDraft]
    ) -> dict[str, DimensionInference]:
        evidence: dict[str, list[_Evidence]] = defaultdict(list)
        resistance: Counter[tuple[UUID, str]] = Counter()
        for event in events:
            data, kind, sitting = event.event_data, event.event_type, event.session_id
            if kind in {
                SignalEventType.MODALITY_SUGGESTION_DECLINED,
                SignalEventType.MODALITY_SUGGESTION_IGNORED,
            }:
                modality = str(data.get("suggestedModality", ""))
                if modality:
                    resistance[(sitting, modality)] += 1
            elif kind is SignalEventType.CALCULATION_STEP_RESPONSE:
                attempts = self._number(data, "attempts", 1)
                hint = bool(data.get("hintUsed", False))
                if attempts <= 1 and not hint and self._number(data, "responseTimeRatio", 1) <= 0.9:
                    evidence["working_memory_capacity"].append(
                        _Evidence(4, sitting, "calculation step completed without hints")
                    )
                elif attempts > 1 and hint:
                    evidence["cognitive_load_threshold"].append(
                        _Evidence(2, sitting, "multiple attempts with hint use")
                    )
            elif kind is SignalEventType.CALCULATION_COMPLETE:
                total = self._number(data, "totalSteps", 0)
                if total > 0:
                    ratio = self._number(data, "stepsWithHint", 0) / total
                    if ratio > 0.5:
                        evidence["cognitive_load_threshold"].append(
                            _Evidence(2, sitting, "support used throughout calculation")
                        )
                    elif ratio < 0.2:
                        evidence["working_memory_capacity"].append(
                            _Evidence(4, sitting, "calculation completed independently")
                        )
            elif kind is SignalEventType.MANIPULATIVE_PIECE_PLACED:
                if self._number(data, "attempts", 1) >= 3 and not data.get("correct", False):
                    evidence["cognitive_load_threshold"].append(
                        _Evidence(2, sitting, "task needed repeated attempts")
                    )
        results = self._results(evidence)
        for (sitting, modality), count in resistance.items():
            if count >= 3:
                name = f"suggestion_frequency:{modality}:{sitting}"
                results[name] = DimensionInference(
                    dimension=name,
                    value=None,
                    confidence=ConfidenceLevel.LOW,
                    evidence_count=count,
                    notes=("reduce suggestion frequency for this session only",),
                )
        return results

    @staticmethod
    def _results(evidence: dict[str, list[_Evidence]]) -> dict[str, DimensionInference]:
        result = {}
        for name, rows in evidence.items():
            sessions = {row.session_id for row in rows if row.session_id is not None}
            confidence = (
                ConfidenceLevel.HIGH
                if len(sessions) >= 5
                else ConfidenceLevel.MEDIUM
                if len(sessions) >= 3
                else ConfidenceLevel.LOW
            )
            result[name] = DimensionInference(
                dimension=name,
                value=round(sum(row.value for row in rows) / len(rows)),
                confidence=confidence,
                evidence_count=len(rows),
                notes=tuple(dict.fromkeys(row.note for row in rows)),
            )
        return result

    @staticmethod
    def _number(metrics, key: str, default: float) -> float:
        try:
            return float(metrics.get(key, default))
        except (ValueError, TypeError):
            return default
