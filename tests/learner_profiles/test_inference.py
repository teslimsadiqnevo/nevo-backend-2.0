from datetime import UTC, datetime
from uuid import uuid4

from nevo.domain.learner_profiles.vocabulary import (
    ChannelPreferenceStrength,
    ConfidenceLevel,
)
from nevo.domain.signal_events.vocabulary import SignalEventType
from nevo.learner_profiles.entities import ObservedActivity
from nevo.learner_profiles.inference import LearnerProfileInferenceEngine
from nevo.signal_events.entities import SignalEventDraft


def signal(
    event_type: SignalEventType,
    *,
    session_id=None,
    event_data: dict[str, object] | None = None,
) -> SignalEventDraft:
    return SignalEventDraft(
        student_id=uuid4(),
        session_id=session_id or uuid4(),
        event_type=event_type,
        event_data=event_data or {},
        timestamp=datetime(2026, 7, 15, 12, tzinfo=UTC),
    )


def test_cold_start_seeds_only_low_confidence_dimensions() -> None:
    engine = LearnerProfileInferenceEngine()

    result = engine.seed_from_observed_sequence(
        [
            ObservedActivity(
                activity_number=1,
                metrics={"accuracy": 0.9, "completion_time_ratio": 0.8},
            ),
            ObservedActivity(
                activity_number=2,
                metrics={
                    "accuracy": 0.88,
                    "listen_through_ratio": 0.95,
                    "replay_count": 1,
                    "response_time_ratio": 0.82,
                },
            ),
            ObservedActivity(
                activity_number=3,
                metrics={
                    "engagement_score": 0.8,
                    "first_half_consistency": 0.9,
                    "second_half_consistency": 0.55,
                },
            ),
            ObservedActivity(
                activity_number=4,
                metrics={
                    "max_successful_pairs": 7,
                    "accuracy_curve_drop": 0.1,
                    "accuracy": 0.82,
                    "completion_time_ratio": 0.78,
                },
            ),
        ]
    )

    assert result["visual_spatial_preference"].value is ChannelPreferenceStrength.STRONG
    assert result["auditory_preference"].value is ChannelPreferenceStrength.STRONG
    assert (
        result["interactive_kinesthetic_preference"].value
        is ChannelPreferenceStrength.MODERATE
    )
    assert result["working_memory_capacity"].value == 5
    assert result["cognitive_load_threshold"].value == 4
    assert result["attention_span"].value == 2
    assert result["processing_speed"].value == 4
    assert "performance_sensitivity" not in result
    assert {item.confidence for item in result.values()} == {ConfidenceLevel.LOW}


def test_cold_start_does_not_seed_processing_speed_from_single_timing_activity() -> None:
    engine = LearnerProfileInferenceEngine()

    result = engine.seed_from_observed_sequence(
        [
            ObservedActivity(
                activity_number=1,
                metrics={"accuracy": 0.9, "completion_time_ratio": 0.8},
            ),
            ObservedActivity(
                activity_number=2,
                metrics={
                    "accuracy": 0.8,
                    "listen_through_ratio": 0.9,
                    "replay_count": 1,
                    "response_time_ratio": 1.0,
                },
            ),
        ]
    )

    assert "processing_speed" not in result


def test_modality_outcomes_raise_channel_confidence_after_three_sessions() -> None:
    engine = LearnerProfileInferenceEngine()
    sessions = [uuid4(), uuid4(), uuid4()]

    result = engine.infer_from_signal_events(
        [
            signal(
                SignalEventType.MODALITY_SWITCH_OUTCOME,
                session_id=session_id,
                event_data={
                    "modality": "visual",
                    "preSwitchComprehensionScore": 0.45,
                    "preSwitchEngagementScore": 0.4,
                    "comprehensionScore": 0.78,
                    "engagementScore": 0.82,
                },
            )
            for session_id in sessions
        ]
    )

    visual = result["visual_spatial_preference"]
    assert visual.value is ChannelPreferenceStrength.STRONG
    assert visual.confidence is ConfidenceLevel.MEDIUM


def test_declines_reduce_suggestion_frequency_without_lowering_channel_confidence() -> None:
    engine = LearnerProfileInferenceEngine()
    session_id = uuid4()

    result = engine.infer_from_signal_events(
        [
            signal(
                SignalEventType.MODALITY_SUGGESTION_DECLINED,
                session_id=session_id,
                event_data={"suggestedModality": "visual"},
            )
            for _ in range(3)
        ]
    )

    assert "visual_spatial_preference" not in result
    frequency = result[f"suggestion_frequency:visual:{session_id}"]
    assert frequency.value is None
    assert "do not reduce channel confidence" in frequency.notes[0]


def test_calculation_narration_and_manipulative_events_update_dimensions() -> None:
    engine = LearnerProfileInferenceEngine()
    sessions = [uuid4(), uuid4(), uuid4()]

    result = engine.infer_from_signal_events(
        [
            signal(
                SignalEventType.CALCULATION_STEP_RESPONSE,
                session_id=sessions[0],
                event_data={
                    "attempts": 1,
                    "hintUsed": False,
                    "responseTimeRatio": 0.7,
                },
            ),
            signal(
                SignalEventType.CALCULATION_COMPLETE,
                session_id=sessions[1],
                event_data={"stepsWithHint": 1, "totalSteps": 8},
            ),
            signal(
                SignalEventType.NARRATION_REPLAYED,
                session_id=sessions[1],
                event_data={"replayCount": 3},
            ),
            signal(
                SignalEventType.MANIPULATIVE_PIECE_PLACED,
                session_id=sessions[2],
                event_data={"attempts": 1, "correct": True},
            ),
        ]
    )

    assert (
        result["interactive_kinesthetic_preference"].value
        is ChannelPreferenceStrength.STRONG
    )
    assert result["working_memory_capacity"].value == 4
    assert result["auditory_preference"].value is ChannelPreferenceStrength.STRONG


def test_reading_writing_strength_requires_comprehension_not_just_time() -> None:
    engine = LearnerProfileInferenceEngine()

    result = engine.infer_from_signal_events(
        [
            signal(
                SignalEventType.TIME_ON_SEGMENT,
                event_data={
                    "modality": "text",
                    "timeOnSegmentRatio": 1.4,
                    "comprehensionAccuracy": 0.4,
                },
            ),
            signal(
                SignalEventType.TIME_ON_SEGMENT,
                event_data={
                    "modality": "text",
                    "timeOnSegmentRatio": 0.7,
                    "comprehensionAccuracy": 0.9,
                },
            ),
        ]
    )

    reading = result["reading_writing_preference"]
    assert reading.value is ChannelPreferenceStrength.STRONG
    assert reading.evidence_count == 1
