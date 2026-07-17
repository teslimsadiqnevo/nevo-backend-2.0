import json
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
