import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from nevo.ai_gateway.errors import ProviderUnavailableError
from nevo.domain.intelligence.vocabulary import (
    AdaptationMode,
    ContentModality,
    ContentSegmentType,
    DensityLevel,
)
from nevo.domain.learner_profiles.vocabulary import (
    ChannelPreferenceStrength,
    ConfidenceLevel,
)
from nevo.intelligence.adaptation import (
    AdaptationEngineService,
    AdaptationRateLimitState,
    balanced_profile,
    rule_based_adaptation_plan,
)
from nevo.intelligence.entities import (
    AdaptationRequest,
    ChannelPreference,
    ContentSegment,
    LearnerProfileSnapshot,
    RuntimeSignals,
)

STUDENT_ID = UUID("00000000-0000-4000-8000-000000000001")
LESSON_ID = UUID("00000000-0000-4000-8000-000000000002")
REQUESTER_ID = UUID("00000000-0000-4000-8000-000000000003")


class FakeProfiles:
    def __init__(self, profile: LearnerProfileSnapshot) -> None:
        self.profile = profile

    async def get_profile(self, student_id: UUID) -> LearnerProfileSnapshot:
        assert student_id == STUDENT_ID
        return self.profile


class FakeGateway:
    def __init__(self, text: str | None = None, fail: bool = False) -> None:
        self.text = text or "{}"
        self.fail = fail
        self.calls = 0

    async def generate(self, request: object) -> object:
        self.calls += 1
        if self.fail:
            raise ProviderUnavailableError
        return SimpleNamespace(text=self.text)


class FakeRateLimits:
    def __init__(
        self,
        *,
        last_adaptation_at=None,
        modality_shift_count=0,
    ) -> None:
        self.state_value = AdaptationRateLimitState(
            last_adaptation_at=last_adaptation_at,
            modality_shift_count=modality_shift_count,
        )
        self.logged = []

    async def state(self, *, student_id, session_id):
        return self.state_value

    async def log_suppressed(self, *, request, attempt, timestamp):
        self.logged.append((request, attempt, timestamp))


def channel_profile() -> LearnerProfileSnapshot:
    low = ChannelPreference(value=None, confidence=ConfidenceLevel.LOW)
    return LearnerProfileSnapshot(
        visual_spatial_preference=ChannelPreference(
            value=ChannelPreferenceStrength.STRONG,
            confidence=ConfidenceLevel.HIGH,
        ),
        auditory_preference=low,
        reading_writing_preference=ChannelPreference(
            value=ChannelPreferenceStrength.MODERATE,
            confidence=ConfidenceLevel.MEDIUM,
        ),
        interactive_kinesthetic_preference=low,
        working_memory_capacity=2,
    )


def segments() -> tuple[ContentSegment, ...]:
    return (
        ContentSegment(
            id="text-1",
            segment_type=ContentSegmentType.EXPLANATION,
            available_modalities=(ContentModality.TEXT,),
            passive=True,
        ),
        ContentSegment(
            id="diagram-1",
            segment_type=ContentSegmentType.DIAGRAM,
            available_modalities=(ContentModality.VISUAL, ContentModality.TEXT),
        ),
    )


def test_rule_based_adaptation_prioritizes_four_channel_profile() -> None:
    plan = rule_based_adaptation_plan(
        request=AdaptationRequest(
            student_id=STUDENT_ID,
            lesson_id=LESSON_ID,
            mode=AdaptationMode.LESSON_LOAD,
            segments=segments(),
        ),
        profile=channel_profile(),
    )

    assert plan.source == "rule_based"
    assert plan.segments[0].segment_id == "diagram-1"
    assert plan.segments[0].modality is ContentModality.VISUAL
    assert plan.segments[1].density is DensityLevel.LOW


def test_rule_based_adaptation_requires_all_three_modality_signals() -> None:
    plan = rule_based_adaptation_plan(
        request=AdaptationRequest(
            student_id=STUDENT_ID,
            lesson_id=LESSON_ID,
            mode=AdaptationMode.IN_LESSON,
            segments=segments(),
            signals=RuntimeSignals(
                current_modality=ContentModality.TEXT,
                available_modalities=(
                    ContentModality.TEXT,
                    ContentModality.VISUAL,
                ),
                engagement_below_baseline_seconds=190,
                accuracy_below_baseline=True,
                segments_since_last_suggestion=2,
            ),
        ),
        profile=channel_profile(),
    )

    assert plan.modality_suggestion is not None
    assert plan.modality_suggestion.suggested is ContentModality.VISUAL
    assert plan.modality_suggestion.trigger_reason == "combined"
    assert plan.modality_suggestion.adaptation_confidence >= 0.6
    assert {
        signal.category for signal in plan.modality_suggestion.trigger_signals
    }.issuperset({"comprehension", "engagement", "profile"})


def test_rule_based_adaptation_ignores_single_pause_signal() -> None:
    plan = rule_based_adaptation_plan(
        request=AdaptationRequest(
            student_id=STUDENT_ID,
            lesson_id=LESSON_ID,
            mode=AdaptationMode.IN_LESSON,
            segments=segments(),
            signals=RuntimeSignals(
                current_modality=ContentModality.TEXT,
                available_modalities=(ContentModality.TEXT, ContentModality.VISUAL),
                current_segment_elapsed_seconds=30,
            ),
        ),
        profile=channel_profile(),
    )

    assert plan.modality_suggestion is None
    assert plan.proactive_adjustment is None


def test_rule_based_adaptation_requires_subsequent_confidence_threshold() -> None:
    plan = rule_based_adaptation_plan(
        request=AdaptationRequest(
            student_id=STUDENT_ID,
            lesson_id=LESSON_ID,
            mode=AdaptationMode.IN_LESSON,
            segments=segments(),
            signals=RuntimeSignals(
                current_modality=ContentModality.TEXT,
                available_modalities=(ContentModality.TEXT, ContentModality.VISUAL),
                engagement_below_baseline_seconds=190,
                accuracy_below_baseline=True,
                response_time_below_baseline=True,
                segments_since_last_suggestion=2,
                session_modality_shift_count=1,
            ),
        ),
        profile=channel_profile(),
    )

    assert plan.modality_suggestion is not None
    assert plan.modality_suggestion.adaptation_confidence >= 0.7


def test_rule_based_adaptation_blocks_consecutive_modality_suggestions() -> None:
    plan = rule_based_adaptation_plan(
        request=AdaptationRequest(
            student_id=STUDENT_ID,
            lesson_id=LESSON_ID,
            mode=AdaptationMode.IN_LESSON,
            segments=segments(),
            signals=RuntimeSignals(
                current_modality=ContentModality.TEXT,
                available_modalities=(ContentModality.VISUAL,),
                engagement_below_baseline_seconds=190,
                accuracy_below_baseline=True,
                segments_since_last_suggestion=1,
            ),
        ),
        profile=channel_profile(),
    )

    assert plan.modality_suggestion is None


@pytest.mark.asyncio
async def test_adaptation_engine_uses_gemini_on_lesson_load() -> None:
    gateway = FakeGateway(
        json.dumps(
            {
                "segments": [
                    {
                        "segment_id": "diagram-1",
                        "modality": "visual",
                        "density": "medium",
                        "scaffolding": "standard",
                        "priority": 90,
                    }
                ]
            }
        )
    )
    service = AdaptationEngineService(
        profiles=FakeProfiles(channel_profile()),
        gateway=gateway,  # type: ignore[arg-type]
    )

    plan = await service.adapt(
        request=AdaptationRequest(
            student_id=STUDENT_ID,
            lesson_id=LESSON_ID,
            mode=AdaptationMode.LESSON_LOAD,
            segments=segments(),
        ),
        requested_by_user_id=REQUESTER_ID,
    )

    assert gateway.calls == 1
    assert plan.source == "gemini"
    assert plan.segments[0].priority == 90


@pytest.mark.asyncio
async def test_adaptation_engine_falls_back_when_gemini_unavailable() -> None:
    service = AdaptationEngineService(
        profiles=FakeProfiles(balanced_profile()),
        gateway=FakeGateway(fail=True),  # type: ignore[arg-type]
    )

    plan = await service.adapt(
        request=AdaptationRequest(
            student_id=STUDENT_ID,
            lesson_id=LESSON_ID,
            mode=AdaptationMode.LESSON_LOAD,
            segments=segments(),
        ),
        requested_by_user_id=REQUESTER_ID,
    )

    assert plan.source == "rule_based"
    assert plan.segments


@pytest.mark.asyncio
async def test_adaptation_engine_suppresses_rapid_modality_shift_before_dwell_time() -> None:
    rate_limits = FakeRateLimits()
    service = AdaptationEngineService(
        profiles=FakeProfiles(channel_profile()),
        gateway=FakeGateway(),  # type: ignore[arg-type]
        rate_limits=rate_limits,
    )

    plan = await service.adapt(
        request=AdaptationRequest(
            student_id=STUDENT_ID,
            lesson_id=LESSON_ID,
            session_id=UUID("00000000-0000-4000-8000-000000000004"),
            mode=AdaptationMode.IN_LESSON,
            segments=segments(),
            signals=RuntimeSignals(
                current_segment_id="diagram-1",
                current_modality=ContentModality.TEXT,
                available_modalities=(ContentModality.TEXT, ContentModality.VISUAL),
                engagement_below_baseline_seconds=190,
                accuracy_below_baseline=True,
                segments_since_last_suggestion=2,
                current_segment_elapsed_seconds=30,
            ),
        ),
        requested_by_user_id=REQUESTER_ID,
    )

    assert plan.modality_suggestion is None
    assert plan.suppressed_attempt is not None
    assert plan.suppressed_attempt.reason == "minimum_dwell_time"
    assert len(rate_limits.logged) == 1


@pytest.mark.asyncio
async def test_adaptation_engine_suppresses_during_cooldown_from_history() -> None:
    service = AdaptationEngineService(
        profiles=FakeProfiles(channel_profile()),
        gateway=FakeGateway(),  # type: ignore[arg-type]
        rate_limits=FakeRateLimits(last_adaptation_at=datetime.now(UTC)),
    )

    plan = await service.adapt(
        request=AdaptationRequest(
            student_id=STUDENT_ID,
            lesson_id=LESSON_ID,
            session_id=UUID("00000000-0000-4000-8000-000000000004"),
            mode=AdaptationMode.IN_LESSON,
            segments=segments(),
            signals=RuntimeSignals(
                current_segment_id="diagram-1",
                current_modality=ContentModality.TEXT,
                available_modalities=(ContentModality.TEXT, ContentModality.VISUAL),
                engagement_below_baseline_seconds=190,
                accuracy_below_baseline=True,
                segments_since_last_suggestion=2,
                current_segment_elapsed_seconds=120,
            ),
        ),
        requested_by_user_id=REQUESTER_ID,
    )

    assert plan.modality_suggestion is None
    assert plan.suppressed_attempt is not None
    assert plan.suppressed_attempt.reason == "adaptation_cooldown"


@pytest.mark.asyncio
async def test_adaptation_engine_caps_modality_shifts_per_session() -> None:
    service = AdaptationEngineService(
        profiles=FakeProfiles(channel_profile()),
        gateway=FakeGateway(),  # type: ignore[arg-type]
        rate_limits=FakeRateLimits(modality_shift_count=3),
    )

    plan = await service.adapt(
        request=AdaptationRequest(
            student_id=STUDENT_ID,
            lesson_id=LESSON_ID,
            session_id=UUID("00000000-0000-4000-8000-000000000004"),
            mode=AdaptationMode.IN_LESSON,
            segments=segments(),
            signals=RuntimeSignals(
                current_segment_id="diagram-1",
                current_modality=ContentModality.TEXT,
                available_modalities=(ContentModality.TEXT, ContentModality.VISUAL),
                engagement_below_baseline_seconds=190,
                accuracy_below_baseline=True,
                segments_since_last_suggestion=2,
                current_segment_elapsed_seconds=120,
            ),
        ),
        requested_by_user_id=REQUESTER_ID,
    )

    assert plan.modality_suggestion is None
    assert plan.suppressed_attempt is not None
    assert plan.suppressed_attempt.reason == "session_modality_shift_cap"
