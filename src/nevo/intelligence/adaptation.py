import json
from collections.abc import Iterable, Mapping
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.ai_gateway.entities import AiGenerationRequest
from nevo.ai_gateway.errors import AiGatewayError
from nevo.ai_gateway.service import AiGatewayService
from nevo.db.models.learner_profile import LearnerProfile
from nevo.domain.ai_gateway.vocabulary import AiService
from nevo.domain.intelligence.vocabulary import (
    AdaptationMode,
    ContentModality,
    ContentSegmentType,
    DensityLevel,
    ScaffoldingLevel,
)
from nevo.domain.learner_profiles.vocabulary import (
    ChannelPreferenceStrength,
    ConfidenceLevel,
)
from nevo.intelligence.breaks import monitor_break_thresholds
from nevo.intelligence.entities import (
    AdaptationPlan,
    AdaptationRequest,
    ChannelPreference,
    ContentSegment,
    LearnerProfileSnapshot,
    ModalitySuggestion,
    ProactiveAdjustment,
    RuntimeSignals,
    SegmentAdaptation,
)

MODALITY_BY_CHANNEL = {
    "visual_spatial_preference": ContentModality.VISUAL,
    "auditory_preference": ContentModality.AUDIO,
    "reading_writing_preference": ContentModality.TEXT,
    "interactive_kinesthetic_preference": ContentModality.INTERACTIVE,
}
CHANNEL_BY_MODALITY = {
    modality: channel for channel, modality in MODALITY_BY_CHANNEL.items()
}
SEGMENT_TYPE_PRIORITY = {
    "visual_spatial_preference": {
        ContentSegmentType.DIAGRAM,
        ContentSegmentType.WORKED_EXAMPLE,
    },
    "auditory_preference": {
        ContentSegmentType.EXPLANATION,
        ContentSegmentType.CHECKPOINT,
    },
    "reading_writing_preference": {
        ContentSegmentType.EXPLANATION,
        ContentSegmentType.DEFINITION,
        ContentSegmentType.SUMMARY,
        ContentSegmentType.WORKED_EXAMPLE,
    },
    "interactive_kinesthetic_preference": {
        ContentSegmentType.PRACTICE,
        ContentSegmentType.INTERACTION,
        ContentSegmentType.CHECKPOINT,
    },
}


class LearnerProfileRepository(Protocol):
    async def get_profile(self, student_id: UUID) -> LearnerProfileSnapshot: ...


class AdaptationEngineService:
    def __init__(
        self,
        *,
        profiles: LearnerProfileRepository,
        gateway: AiGatewayService,
    ) -> None:
        self._profiles = profiles
        self._gateway = gateway

    async def adapt(
        self,
        *,
        request: AdaptationRequest,
        requested_by_user_id: UUID,
    ) -> AdaptationPlan:
        profile = await self._profiles.get_profile(request.student_id)
        fallback_plan = rule_based_adaptation_plan(request=request, profile=profile)
        if request.mode is AdaptationMode.IN_LESSON:
            return fallback_plan

        try:
            result = await self._gateway.generate(
                AiGenerationRequest(
                    requester_user_id=requested_by_user_id,
                    student_id=request.student_id,
                    service=AiService.ADAPTATION,
                    prompt_name="adaptation.default",
                    variables={
                        "source_text": json.dumps(
                            _segments_for_prompt(request.segments),
                            sort_keys=True,
                        ),
                        "instruction": json.dumps(
                            {
                                "lesson_id": str(request.lesson_id),
                                "profile": _profile_for_prompt(profile),
                                "required_shape": {
                                    "segments": [
                                        {
                                            "segment_id": "string",
                                            "modality": "visual|audio|text|interactive",
                                            "density": "low|medium|high",
                                            "scaffolding": "light|standard|strong",
                                            "priority": 0,
                                        }
                                    ]
                                },
                            },
                            sort_keys=True,
                        ),
                    },
                    max_output_tokens=2_048,
                )
            )
        except AiGatewayError:
            return fallback_plan

        gemini_plan = parse_gemini_adaptation_plan(
            lesson_id=request.lesson_id,
            response_text=result.text,
            fallback_plan=fallback_plan,
        )
        return gemini_plan or fallback_plan


def rule_based_adaptation_plan(
    *,
    request: AdaptationRequest,
    profile: LearnerProfileSnapshot,
) -> AdaptationPlan:
    active_channels = _active_channels(profile)
    segments = tuple(
        sorted(
            (
                _adapt_segment(segment, active_channels, profile)
                for segment in request.segments
            ),
            key=lambda item: item.priority,
            reverse=True,
        )
    )
    break_suggestion = monitor_break_thresholds(
        signals=request.signals,
        profile=profile,
    )
    return AdaptationPlan(
        lesson_id=request.lesson_id,
        segments=segments,
        break_suggestion=break_suggestion,
        proactive_adjustment=_proactive_adjustment(request.signals),
        modality_suggestion=_modality_suggestion(
            signals=request.signals,
            profile=profile,
        ),
        source="rule_based",
    )


def parse_gemini_adaptation_plan(
    *,
    lesson_id: UUID,
    response_text: str,
    fallback_plan: AdaptationPlan,
) -> AdaptationPlan | None:
    try:
        payload = json.loads(_json_payload(response_text))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    items = payload.get("segments")
    if not isinstance(items, list):
        return None

    adapted: list[SegmentAdaptation] = []
    fallback_by_id = {item.segment_id: item for item in fallback_plan.segments}
    for item in items:
        if not isinstance(item, dict):
            continue
        segment_id = str(item.get("segment_id") or item.get("id") or "")
        fallback = fallback_by_id.get(segment_id)
        if fallback is None:
            continue
        try:
            adapted.append(
                SegmentAdaptation(
                    segment_id=segment_id,
                    modality=ContentModality(str(item.get("modality"))),
                    density=DensityLevel(str(item.get("density"))),
                    scaffolding=ScaffoldingLevel(str(item.get("scaffolding"))),
                    priority=int(item.get("priority", fallback.priority)),
                )
            )
        except (ValueError, TypeError):
            adapted.append(fallback)
    if not adapted:
        return None
    return AdaptationPlan(
        lesson_id=lesson_id,
        segments=tuple(adapted),
        break_suggestion=fallback_plan.break_suggestion,
        proactive_adjustment=fallback_plan.proactive_adjustment,
        modality_suggestion=fallback_plan.modality_suggestion,
        source="gemini",
    )


class SqlAlchemyLearnerProfileRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get_profile(self, student_id: UUID) -> LearnerProfileSnapshot:
        async with self._sessions() as session:
            profile = await session.scalar(
                select(LearnerProfile).where(
                    LearnerProfile.learner_id == student_id
                )
            )
        if profile is None:
            return balanced_profile()
        return LearnerProfileSnapshot(
            visual_spatial_preference=ChannelPreference(
                value=profile.visual_spatial_preference,
                confidence=profile.visual_spatial_preference_confidence,
            ),
            auditory_preference=ChannelPreference(
                value=profile.auditory_preference,
                confidence=profile.auditory_preference_confidence,
            ),
            reading_writing_preference=ChannelPreference(
                value=profile.reading_writing_preference,
                confidence=profile.reading_writing_preference_confidence,
            ),
            interactive_kinesthetic_preference=ChannelPreference(
                value=profile.interactive_kinesthetic_preference,
                confidence=profile.interactive_kinesthetic_preference_confidence,
            ),
            working_memory_capacity=profile.working_memory_capacity,
            attention_span=profile.attention_span,
        )


def balanced_profile() -> LearnerProfileSnapshot:
    low = ChannelPreference(value=None, confidence=ConfidenceLevel.LOW)
    return LearnerProfileSnapshot(
        visual_spatial_preference=low,
        auditory_preference=low,
        reading_writing_preference=low,
        interactive_kinesthetic_preference=low,
    )


def _adapt_segment(
    segment: ContentSegment,
    active_channels: tuple[str, ...],
    profile: LearnerProfileSnapshot,
) -> SegmentAdaptation:
    modality = _preferred_modality(segment, active_channels)
    priority = _segment_priority(segment, active_channels)
    density = DensityLevel.MEDIUM
    scaffolding = ScaffoldingLevel.STANDARD
    if (
        segment.segment_type is ContentSegmentType.EXPLANATION
        and ContentModality.TEXT in segment.available_modalities
        and "visual_spatial_preference" in active_channels
    ):
        density = DensityLevel.LOW
        scaffolding = ScaffoldingLevel.STRONG
    if (
        "reading_writing_preference" in active_channels
        and segment.segment_type
        in {
            ContentSegmentType.DEFINITION,
            ContentSegmentType.SUMMARY,
            ContentSegmentType.EXPLANATION,
        }
    ):
        density = DensityLevel.HIGH
    if (
        profile.working_memory_capacity is not None
        and profile.working_memory_capacity <= 2
    ):
        scaffolding = ScaffoldingLevel.STRONG
        density = DensityLevel.LOW
    return SegmentAdaptation(
        segment_id=segment.id,
        modality=modality,
        density=density,
        scaffolding=scaffolding,
        priority=priority,
    )


def _active_channels(profile: LearnerProfileSnapshot) -> tuple[str, ...]:
    channels: list[str] = []
    for channel, preference in _profile_channels(profile).items():
        if preference.value in {
            ChannelPreferenceStrength.MODERATE,
            ChannelPreferenceStrength.STRONG,
        }:
            channels.append(channel)
    return tuple(channels)


def _preferred_modality(
    segment: ContentSegment,
    active_channels: tuple[str, ...],
) -> ContentModality:
    for channel in active_channels:
        modality = MODALITY_BY_CHANNEL[channel]
        if modality in segment.available_modalities:
            return modality
    if segment.available_modalities:
        return segment.available_modalities[0]
    return ContentModality.TEXT


def _segment_priority(
    segment: ContentSegment,
    active_channels: tuple[str, ...],
) -> int:
    if not active_channels:
        return 50
    priority = 50
    for channel in active_channels:
        if segment.segment_type in SEGMENT_TYPE_PRIORITY[channel]:
            priority += 20
        if MODALITY_BY_CHANNEL[channel] in segment.available_modalities:
            priority += 10
    return priority


def _proactive_adjustment(signals: RuntimeSignals) -> ProactiveAdjustment | None:
    if (
        signals.comprehension_score is not None
        and signals.session_average_comprehension is not None
        and signals.session_average_comprehension - signals.comprehension_score >= 20
    ):
        return ProactiveAdjustment(
            action="simplify",
            reason="Comprehension has dropped below this session's average.",
        )
    if signals.replay_count_on_segment >= 3:
        return ProactiveAdjustment(
            action="slower",
            reason="Replay accumulation suggests the segment pace is too high.",
        )
    if (
        signals.engagement_score is not None
        and signals.engagement_baseline is not None
        and signals.engagement_score >= signals.engagement_baseline + 0.2
    ):
        return ProactiveAdjustment(
            action="expand",
            reason="Engagement is above the current baseline.",
        )
    return None


def _modality_suggestion(
    *,
    signals: RuntimeSignals,
    profile: LearnerProfileSnapshot,
) -> ModalitySuggestion | None:
    if not _modality_constraints_allow(signals):
        return None
    if not _comprehension_declining(signals) or not _engagement_declining(signals):
        return None
    if signals.current_modality is None:
        return None

    current_channel = CHANNEL_BY_MODALITY.get(signals.current_modality)
    current_confidence = (
        _profile_channels(profile)[current_channel].confidence
        if current_channel is not None
        else ConfidenceLevel.LOW
    )
    candidate = _higher_confidence_available_channel(
        profile=profile,
        current_confidence=current_confidence,
        available_modalities=signals.available_modalities,
        declined_modalities=signals.declined_modalities,
    )
    if candidate is None:
        return None
    return ModalitySuggestion(
        suggested=MODALITY_BY_CHANNEL[candidate],
        trigger_reason="combined",
        confidence=_profile_channels(profile)[candidate].confidence,
    )


def _modality_constraints_allow(signals: RuntimeSignals) -> bool:
    if signals.same_segment_suggestion_shown:
        return False
    if (
        signals.segments_since_last_suggestion is not None
        and signals.segments_since_last_suggestion < 2
    ):
        return False
    if signals.session_decline_count >= 2:
        return False
    return True


def _comprehension_declining(signals: RuntimeSignals) -> bool:
    return signals.accuracy_below_baseline or signals.response_time_below_baseline


def _engagement_declining(signals: RuntimeSignals) -> bool:
    if signals.engagement_below_baseline_seconds >= 180:
        return True
    if signals.replay_count_on_segment >= 3:
        return True
    if (
        signals.engagement_score is not None
        and signals.engagement_baseline is not None
    ):
        return signals.engagement_score <= signals.engagement_baseline - 0.15
    return False


def _higher_confidence_available_channel(
    *,
    profile: LearnerProfileSnapshot,
    current_confidence: ConfidenceLevel,
    available_modalities: tuple[ContentModality, ...],
    declined_modalities: tuple[ContentModality, ...],
) -> str | None:
    confidence_rank = {
        ConfidenceLevel.LOW: 1,
        ConfidenceLevel.MEDIUM: 2,
        ConfidenceLevel.HIGH: 3,
    }
    candidates: list[tuple[int, str]] = []
    for channel, preference in _profile_channels(profile).items():
        modality = MODALITY_BY_CHANNEL[channel]
        if modality not in available_modalities or modality in declined_modalities:
            continue
        if preference.value not in {
            ChannelPreferenceStrength.MODERATE,
            ChannelPreferenceStrength.STRONG,
        }:
            continue
        rank = confidence_rank[preference.confidence]
        if rank > confidence_rank[current_confidence]:
            candidates.append((rank, channel))
    if not candidates:
        return None
    return sorted(candidates, reverse=True)[0][1]


def _profile_channels(
    profile: LearnerProfileSnapshot,
) -> Mapping[str, ChannelPreference]:
    return {
        "visual_spatial_preference": profile.visual_spatial_preference,
        "auditory_preference": profile.auditory_preference,
        "reading_writing_preference": profile.reading_writing_preference,
        "interactive_kinesthetic_preference": (
            profile.interactive_kinesthetic_preference
        ),
    }


def _segments_for_prompt(segments: Iterable[ContentSegment]) -> list[dict[str, object]]:
    return [
        {
            "id": segment.id,
            "concept_id": segment.concept_id,
            "segment_type": segment.segment_type.value,
            "available_modalities": [
                modality.value for modality in segment.available_modalities
            ],
            "estimated_minutes": segment.estimated_minutes,
            "passive": segment.passive,
            "title": segment.title,
        }
        for segment in segments
    ]


def _profile_for_prompt(profile: LearnerProfileSnapshot) -> dict[str, object]:
    return {
        channel: {
            "value": preference.value.value if preference.value is not None else None,
            "confidence": preference.confidence.value,
        }
        for channel, preference in _profile_channels(profile).items()
    }


def _json_payload(response_text: str) -> str:
    stripped = response_text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 3 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped
