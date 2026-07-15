from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from nevo.domain.learner_profiles.vocabulary import (
    ChannelPreferenceStrength,
    ConfidenceLevel,
)
from nevo.domain.signal_events.vocabulary import SignalEventType
from nevo.learner_profiles.entities import DimensionInference, ObservedActivity
from nevo.signal_events.entities import SignalEventDraft

CHANNEL_BY_MODALITY = {
    "visual": "visual_spatial_preference",
    "diagram": "visual_spatial_preference",
    "spatial": "visual_spatial_preference",
    "audio": "auditory_preference",
    "auditory": "auditory_preference",
    "narration": "auditory_preference",
    "text": "reading_writing_preference",
    "reading": "reading_writing_preference",
    "writing": "reading_writing_preference",
    "interactive": "interactive_kinesthetic_preference",
    "kinesthetic": "interactive_kinesthetic_preference",
    "manipulative": "interactive_kinesthetic_preference",
}


@dataclass(frozen=True, slots=True)
class _Evidence:
    value: int | ChannelPreferenceStrength | None
    session_id: UUID | None
    note: str


class LearnerProfileInferenceEngine:
    def seed_from_observed_sequence(
        self,
        activities: Iterable[ObservedActivity],
    ) -> dict[str, DimensionInference]:
        channel_evidence: dict[str, list[ChannelPreferenceStrength]] = defaultdict(list)
        timing_votes: list[int] = []
        numeric_evidence: dict[str, list[_Evidence]] = defaultdict(list)

        for activity in activities:
            metrics = activity.metrics
            if activity.activity_number == 1:
                visual = self._strength_from_score(
                    self._number(metrics, "accuracy", 0.0),
                    strong=0.85,
                    moderate=0.6,
                )
                channel_evidence["visual_spatial_preference"].append(visual)
                speed = self._speed_from_ratio(
                    self._number(metrics, "completion_time_ratio", 1.0)
                )
                if speed is not None:
                    timing_votes.append(speed)

            elif activity.activity_number == 2:
                replay_count = self._number(metrics, "replay_count", 0)
                accuracy = self._number(metrics, "accuracy", 0.0)
                listen_ratio = self._number(metrics, "listen_through_ratio", 0.0)
                if listen_ratio >= 0.8 and accuracy >= 0.75 and replay_count <= 1:
                    channel_evidence["auditory_preference"].append(
                        ChannelPreferenceStrength.STRONG
                        if accuracy >= 0.85
                        else ChannelPreferenceStrength.MODERATE
                    )
                speed = self._speed_from_ratio(
                    self._number(metrics, "response_time_ratio", 1.0)
                )
                if speed is not None:
                    timing_votes.append(speed)

            elif activity.activity_number == 3:
                engagement = self._number(metrics, "engagement_score", 0.0)
                if engagement >= 0.65:
                    channel_evidence["interactive_kinesthetic_preference"].append(
                        ChannelPreferenceStrength.MODERATE
                    )
                first_half = self._number(metrics, "first_half_consistency", 0.0)
                second_half = self._number(metrics, "second_half_consistency", first_half)
                if first_half - second_half >= 0.25:
                    numeric_evidence["attention_span"].append(
                        _Evidence(2, None, "within-task consistency decay observed")
                    )

            elif activity.activity_number == 4:
                max_pairs = self._number(metrics, "max_successful_pairs", 0)
                curve_drop = self._number(metrics, "accuracy_curve_drop", 0.0)
                numeric_evidence["working_memory_capacity"].append(
                    _Evidence(
                        self._working_memory_from_pairs(max_pairs, curve_drop),
                        None,
                        "working-memory matching curve",
                    )
                )
                numeric_evidence["cognitive_load_threshold"].append(
                    _Evidence(
                        4 if max_pairs >= 6 and curve_drop <= 0.25 else 2,
                        None,
                        "rough cold-start load seed",
                    )
                )
                if self._number(metrics, "accuracy", 0.0) >= 0.7:
                    channel_evidence["interactive_kinesthetic_preference"].append(
                        ChannelPreferenceStrength.MODERATE
                    )
                speed = self._speed_from_ratio(
                    self._number(metrics, "completion_time_ratio", 1.0)
                )
                if speed is not None:
                    timing_votes.append(speed)

        results: dict[str, DimensionInference] = {}
        for dimension, strengths in channel_evidence.items():
            results[dimension] = DimensionInference(
                dimension=dimension,
                value=self._strongest(strengths),
                confidence=ConfidenceLevel.LOW,
                evidence_count=len(strengths),
                notes=("cold-start seed; requires real-session corroboration",),
            )

        for dimension, evidence in numeric_evidence.items():
            results[dimension] = DimensionInference(
                dimension=dimension,
                value=round(sum(int(item.value or 0) for item in evidence) / len(evidence)),
                confidence=ConfidenceLevel.LOW,
                evidence_count=len(evidence),
                notes=tuple(item.note for item in evidence),
            )

        speed_seed = self._consistent_speed_seed(timing_votes)
        if speed_seed is not None:
            results["processing_speed"] = DimensionInference(
                dimension="processing_speed",
                value=speed_seed,
                confidence=ConfidenceLevel.LOW,
                evidence_count=len(timing_votes),
                notes=("timing pattern appeared across 2+ timing activities",),
            )

        return results

    def infer_from_signal_events(
        self,
        events: Iterable[SignalEventDraft],
    ) -> dict[str, DimensionInference]:
        channel_evidence: dict[str, list[_Evidence]] = defaultdict(list)
        numeric_evidence: dict[str, list[_Evidence]] = defaultdict(list)
        suggestion_resistance: Counter[tuple[UUID, str]] = Counter()

        for event in events:
            data = event.event_data
            event_type = event.event_type
            session_id = event.session_id

            if event_type is SignalEventType.MODALITY_SWITCH_OUTCOME:
                modality = str(data.get("modality", ""))
                dimension = CHANNEL_BY_MODALITY.get(modality)
                if dimension and self._switch_improved(data):
                    channel_evidence[dimension].append(
                        _Evidence(
                            ChannelPreferenceStrength.STRONG,
                            session_id,
                            "modality switch improved comprehension and engagement",
                        )
                    )

            elif event_type in {
                SignalEventType.MODALITY_SUGGESTION_DECLINED,
                SignalEventType.MODALITY_SUGGESTION_IGNORED,
            }:
                modality = str(data.get("suggestedModality", ""))
                if modality:
                    suggestion_resistance[(session_id, modality)] += 1

            elif event_type is SignalEventType.CALCULATION_STEP_RESPONSE:
                attempts = self._number(data, "attempts", 1)
                hint_used = bool(data.get("hintUsed", False))
                response_time = self._number(data, "responseTimeRatio", 1.0)
                if attempts <= 1 and not hint_used and response_time <= 0.9:
                    channel_evidence["interactive_kinesthetic_preference"].append(
                        _Evidence(
                            ChannelPreferenceStrength.STRONG,
                            session_id,
                            "fast calculation step without hints",
                        )
                    )
                    numeric_evidence["working_memory_capacity"].append(
                        _Evidence(4, session_id, "fast calculation step without hints")
                    )
                if attempts > 1 and hint_used:
                    numeric_evidence["cognitive_load_threshold"].append(
                        _Evidence(2, session_id, "multiple attempts with healthy hint use")
                    )

            elif event_type is SignalEventType.CALCULATION_COMPLETE:
                ratio = self._hint_ratio(data)
                if ratio > 0.5:
                    numeric_evidence["cognitive_load_threshold"].append(
                        _Evidence(2, session_id, "support needed throughout calculation")
                    )
                elif ratio < 0.2:
                    numeric_evidence["working_memory_capacity"].append(
                        _Evidence(4, session_id, "calculation completed independently")
                    )

            elif event_type is SignalEventType.NARRATION_REPLAYED:
                if self._number(data, "replayCount", 1) >= 3:
                    channel_evidence["auditory_preference"].append(
                        _Evidence(
                            ChannelPreferenceStrength.STRONG,
                            session_id,
                            "repeated narration replay used as support",
                        )
                    )

            elif event_type is SignalEventType.MANIPULATIVE_PIECE_PLACED:
                attempts = self._number(data, "attempts", 1)
                correct = bool(data.get("correct", False))
                if attempts <= 1 and correct:
                    channel_evidence["interactive_kinesthetic_preference"].append(
                        _Evidence(
                            ChannelPreferenceStrength.STRONG,
                            session_id,
                            "accurate manipulative placement",
                        )
                    )
                elif attempts >= 3 and not correct:
                    numeric_evidence["cognitive_load_threshold"].append(
                        _Evidence(2, session_id, "spatial task needed repeated attempts")
                    )

            elif event_type is SignalEventType.TIME_ON_SEGMENT:
                if str(data.get("modality", "")) == "text":
                    accuracy = self._number(data, "comprehensionAccuracy", -1)
                    time_ratio = self._number(data, "timeOnSegmentRatio", 1.0)
                    if accuracy >= 0.75 and (time_ratio >= 1.1 or time_ratio <= 0.8):
                        channel_evidence["reading_writing_preference"].append(
                            _Evidence(
                                ChannelPreferenceStrength.STRONG,
                                session_id,
                                "text segment completed with strong comprehension",
                            )
                        )

        results = self._results_from_channel_evidence(channel_evidence)
        results.update(self._results_from_numeric_evidence(numeric_evidence))

        for (session_id, modality), count in suggestion_resistance.items():
            if count >= 3:
                dimension = f"suggestion_frequency:{modality}:{session_id}"
                results[dimension] = DimensionInference(
                    dimension=dimension,
                    value=None,
                    confidence=ConfidenceLevel.LOW,
                    evidence_count=count,
                    notes=(
                        "reduce suggestion frequency only; do not reduce channel confidence",
                    ),
                )

        return results

    def _results_from_channel_evidence(
        self,
        evidence_by_dimension: dict[str, list[_Evidence]],
    ) -> dict[str, DimensionInference]:
        results = {}
        for dimension, evidence in evidence_by_dimension.items():
            sessions = {item.session_id for item in evidence if item.session_id is not None}
            confidence = self._confidence_for_sessions(len(sessions))
            results[dimension] = DimensionInference(
                dimension=dimension,
                value=self._strongest(
                    item.value
                    for item in evidence
                    if isinstance(item.value, ChannelPreferenceStrength)
                ),
                confidence=confidence,
                evidence_count=len(evidence),
                notes=tuple(dict.fromkeys(item.note for item in evidence)),
            )
        return results

    def _results_from_numeric_evidence(
        self,
        evidence_by_dimension: dict[str, list[_Evidence]],
    ) -> dict[str, DimensionInference]:
        results = {}
        for dimension, evidence in evidence_by_dimension.items():
            sessions = {item.session_id for item in evidence if item.session_id is not None}
            values = [int(item.value or 0) for item in evidence]
            results[dimension] = DimensionInference(
                dimension=dimension,
                value=round(sum(values) / len(values)),
                confidence=self._confidence_for_sessions(len(sessions)),
                evidence_count=len(evidence),
                notes=tuple(dict.fromkeys(item.note for item in evidence)),
            )
        return results

    @staticmethod
    def _confidence_for_sessions(session_count: int) -> ConfidenceLevel:
        if session_count >= 5:
            return ConfidenceLevel.HIGH
        if session_count >= 3:
            return ConfidenceLevel.MEDIUM
        return ConfidenceLevel.LOW

    @staticmethod
    def _number(
        metrics: dict[str, float | int | str | bool] | dict[str, object],
        key: str,
        default: float,
    ) -> float:
        value = metrics.get(key, default)
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, int | float):
            return float(value)
        try:
            return float(str(value))
        except ValueError:
            return default

    @staticmethod
    def _strength_from_score(
        score: float,
        *,
        strong: float,
        moderate: float,
    ) -> ChannelPreferenceStrength:
        if score >= strong:
            return ChannelPreferenceStrength.STRONG
        if score >= moderate:
            return ChannelPreferenceStrength.MODERATE
        return ChannelPreferenceStrength.LOW

    @staticmethod
    def _strongest(
        strengths: Iterable[ChannelPreferenceStrength],
    ) -> ChannelPreferenceStrength:
        ordered = {
            ChannelPreferenceStrength.LOW: 0,
            ChannelPreferenceStrength.MODERATE: 1,
            ChannelPreferenceStrength.STRONG: 2,
        }
        return max(strengths, key=lambda item: ordered[item])

    @staticmethod
    def _speed_from_ratio(ratio: float) -> int | None:
        if ratio <= 0.85:
            return 4
        if ratio >= 1.2:
            return 2
        return None

    @staticmethod
    def _consistent_speed_seed(votes: list[int]) -> int | None:
        fast = sum(1 for vote in votes if vote >= 4)
        slow = sum(1 for vote in votes if vote <= 2)
        if fast >= 2:
            return 4
        if slow >= 2:
            return 2
        return None

    @staticmethod
    def _working_memory_from_pairs(max_pairs: float, curve_drop: float) -> int:
        if max_pairs >= 7 and curve_drop <= 0.2:
            return 5
        if max_pairs >= 5 and curve_drop <= 0.35:
            return 4
        if max_pairs >= 3:
            return 3
        return 2

    @classmethod
    def _switch_improved(cls, data: dict[str, object]) -> bool:
        comprehension = cls._number(data, "comprehensionScore", 0)
        engagement = cls._number(data, "engagementScore", 0)
        previous_comprehension = cls._number(data, "preSwitchComprehensionScore", 0)
        previous_engagement = cls._number(data, "preSwitchEngagementScore", 0)
        return (
            comprehension > previous_comprehension
            and engagement > previous_engagement
        )

    @classmethod
    def _hint_ratio(cls, data: dict[str, object]) -> float:
        total_steps = cls._number(data, "totalSteps", 0)
        if total_steps <= 0:
            return 0
        return cls._number(data, "stepsWithHint", 0) / total_steps

