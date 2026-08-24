import json
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.ai_gateway.entities import AiGenerationRequest
from nevo.ai_gateway.errors import AiGatewayError
from nevo.ai_gateway.service import AiGatewayService
from nevo.db.models.learner_profile import LearnerProfile
from nevo.db.models.signal_event import SignalEvent
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
from nevo.domain.signal_events.vocabulary import SignalEventType
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
    SuppressedAdaptationAttempt,
    TriggerSignal,
)

FIRST_ADAPTATION_CONFIDENCE_THRESHOLD = 0.60
SUBSEQUENT_ADAPTATION_CONFIDENCE_THRESHOLD = 0.70
MIN_ALIGNED_SIGNAL_COUNT = 3
MIN_ALIGNED_SIGNAL_CATEGORIES = 2
MIN_MODALITY_DWELL_SECONDS = 90
ADAPTATION_COOLDOWN_SECONDS = 120
MAX_MODALITY_SHIFTS_PER_SESSION = 3
MODALITY_BY_CHANNEL = {
    "visual_spatial_preference": ContentModality.VISUAL,
    "auditory_preference": ContentModality.AUDIO,
    "reading_writing_preference": ContentModality.TEXT,
    "interactive_kinesthetic_preference": ContentModality.INTERACTIVE,
}
ADAPTATION_HISTORY_EVENT_TYPES = {
    SignalEventType.SIMPLIFY_TRIGGER,
    SignalEventType.EXPAND_TRIGGER,
    SignalEventType.SLOWER_TRIGGER,
    SignalEventType.BREAK_SUGGESTED,
    SignalEventType.MODALITY_SUGGESTION_SHOWN,
    SignalEventType.MODALITY_SUGGESTION_ACCEPTED,
    SignalEventType.MODALITY_SWITCH_OUTCOME,
    SignalEventType.MODALITY_MANUAL_SWITCH,
}
MODALITY_SHIFT_EVENT_TYPES = {
    SignalEventType.MODALITY_SUGGESTION_ACCEPTED,
    SignalEventType.MODALITY_SWITCH_OUTCOME,
    SignalEventType.MODALITY_MANUAL_SWITCH,
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


class AdaptationRateLimitRepository(Protocol):
    async def state(
        self,
        *,
        student_id: UUID,
        session_id: UUID,
    ) -> "AdaptationRateLimitState": ...

    async def log_suppressed(
        self,
        *,
        request: AdaptationRequest,
        attempt: SuppressedAdaptationAttempt,
        timestamp: datetime,
    ) -> None: ...


class AdaptationRateLimitState:
    def __init__(
        self,
        *,
        last_adaptation_at: datetime | None,
        modality_shift_count: int,
    ) -> None:
        self.last_adaptation_at = last_adaptation_at
        self.modality_shift_count = modality_shift_count


class AdaptationEngineService:
    def __init__(
        self,
        *,
        profiles: LearnerProfileRepository,
        gateway: AiGatewayService,
        rate_limits: AdaptationRateLimitRepository | None = None,
    ) -> None:
        self._profiles = profiles
        self._gateway = gateway
        self._rate_limits = rate_limits

    async def adapt(
        self,
        *,
        request: AdaptationRequest,
        requested_by_user_id: UUID,
    ) -> AdaptationPlan:
        profile = await self._profiles.get_profile(request.student_id)
        fallback_plan = rule_based_adaptation_plan(request=request, profile=profile)
        if request.mode is AdaptationMode.IN_LESSON:
            return await self._apply_rate_limits(request=request, plan=fallback_plan)

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

    async def _apply_rate_limits(
        self,
        *,
        request: AdaptationRequest,
        plan: AdaptationPlan,
    ) -> AdaptationPlan:
        attempt = _rate_limit_violation_from_signals(request=request, plan=plan)
        now = datetime.now(UTC)
        if attempt is None and self._rate_limits is not None and request.session_id:
            state = await self._rate_limits.state(
                student_id=request.student_id,
                session_id=request.session_id,
            )
            attempt = _rate_limit_violation_from_history(
                request=request,
                plan=plan,
                state=state,
                now=now,
            )
        if attempt is None:
            return plan
        suppressed_plan = _suppress_plan(plan=plan, attempt=attempt)
        if self._rate_limits is not None and request.session_id:
            await self._rate_limits.log_suppressed(
                request=request,
                attempt=attempt,
                timestamp=now,
            )
        return suppressed_plan


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
        proactive_adjustment=_proactive_adjustment(
            signals=request.signals,
            profile=profile,
        ),
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


class SqlAlchemyAdaptationRateLimitRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def state(
        self,
        *,
        student_id: UUID,
        session_id: UUID,
    ) -> AdaptationRateLimitState:
        async with self._sessions() as session:
            last_adaptation_at = await session.scalar(
                select(func.max(SignalEvent.timestamp)).where(
                    SignalEvent.student_id == student_id,
                    SignalEvent.session_id == session_id,
                    SignalEvent.event_type.in_(ADAPTATION_HISTORY_EVENT_TYPES),
                )
            )
            modality_shift_count = int(
                await session.scalar(
                    select(func.count(SignalEvent.id)).where(
                        SignalEvent.student_id == student_id,
                        SignalEvent.session_id == session_id,
                        SignalEvent.event_type.in_(MODALITY_SHIFT_EVENT_TYPES),
                    )
                )
                or 0
            )
        return AdaptationRateLimitState(
            last_adaptation_at=last_adaptation_at,
            modality_shift_count=modality_shift_count,
        )

    async def log_suppressed(
        self,
        *,
        request: AdaptationRequest,
        attempt: SuppressedAdaptationAttempt,
        timestamp: datetime,
    ) -> None:
        if request.session_id is None:
            return
        event_data: dict[str, object] = {
            "lessonId": str(request.lesson_id),
            "attemptedType": attempt.attempted_type,
            "reason": attempt.reason,
        }
        if attempt.current_segment_id is not None:
            event_data["segmentId"] = attempt.current_segment_id
        if attempt.current_modality is not None:
            event_data["currentModality"] = attempt.current_modality.value
        if attempt.suggested_modality is not None:
            event_data["suggestedModality"] = attempt.suggested_modality.value
        event_data["adaptationConfidence"] = attempt.confidence
        event_data["triggerSignals"] = [
            {
                "category": signal.category,
                "name": signal.name,
                "confidence": signal.confidence,
            }
            for signal in attempt.trigger_signals
        ]
        candidate = request.signals
        event_data["signalSnapshot"] = {
            "currentSegmentElapsedSeconds": candidate.current_segment_elapsed_seconds,
            "secondsSinceLastAdaptation": candidate.seconds_since_last_adaptation,
            "sessionModalityShiftCount": candidate.session_modality_shift_count,
            "engagementBelowBaselineSeconds": (
                candidate.engagement_below_baseline_seconds
            ),
            "comprehensionScore": candidate.comprehension_score,
            "sessionAverageComprehension": candidate.session_average_comprehension,
            "consecutiveErrors": candidate.consecutive_errors,
            "replayCountOnSegment": candidate.replay_count_on_segment,
            "accuracyBelowBaseline": candidate.accuracy_below_baseline,
            "responseTimeBelowBaseline": candidate.response_time_below_baseline,
        }
        async with self._sessions.begin() as session:
            await session.execute(
                insert(SignalEvent).values(
                    student_id=request.student_id,
                    session_id=request.session_id,
                    event_type=SignalEventType.ADAPTATION_SUPPRESSED,
                    event_data=event_data,
                    timestamp=timestamp,
                )
            )


def balanced_profile() -> LearnerProfileSnapshot:
    low = ChannelPreference(value=None, confidence=ConfidenceLevel.LOW)
    return LearnerProfileSnapshot(
        visual_spatial_preference=low,
        auditory_preference=low,
        reading_writing_preference=low,
        interactive_kinesthetic_preference=low,
    )


def _rate_limit_violation_from_signals(
    *,
    request: AdaptationRequest,
    plan: AdaptationPlan,
) -> SuppressedAdaptationAttempt | None:
    if not _has_suppressible_adaptation(plan):
        return None
    signals = request.signals
    if (
        plan.modality_suggestion is not None
        and signals.current_segment_elapsed_seconds is not None
        and signals.current_segment_elapsed_seconds < MIN_MODALITY_DWELL_SECONDS
    ):
        return _suppression_attempt(
            request=request,
            plan=plan,
            reason="minimum_dwell_time",
        )
    if (
        signals.seconds_since_last_adaptation is not None
        and signals.seconds_since_last_adaptation < ADAPTATION_COOLDOWN_SECONDS
    ):
        return _suppression_attempt(
            request=request,
            plan=plan,
            reason="adaptation_cooldown",
        )
    if (
        plan.modality_suggestion is not None
        and signals.session_modality_shift_count is not None
        and signals.session_modality_shift_count >= MAX_MODALITY_SHIFTS_PER_SESSION
    ):
        return _suppression_attempt(
            request=request,
            plan=plan,
            reason="session_modality_shift_cap",
        )
    return None


def _rate_limit_violation_from_history(
    *,
    request: AdaptationRequest,
    plan: AdaptationPlan,
    state: AdaptationRateLimitState,
    now: datetime,
) -> SuppressedAdaptationAttempt | None:
    if not _has_suppressible_adaptation(plan):
        return None
    if state.last_adaptation_at is not None:
        seconds_since = (now - state.last_adaptation_at).total_seconds()
        if seconds_since < ADAPTATION_COOLDOWN_SECONDS:
            return _suppression_attempt(
                request=request,
                plan=plan,
                reason="adaptation_cooldown",
            )
    if (
        plan.modality_suggestion is not None
        and state.modality_shift_count >= MAX_MODALITY_SHIFTS_PER_SESSION
    ):
        return _suppression_attempt(
            request=request,
            plan=plan,
            reason="session_modality_shift_cap",
        )
    return None


def _has_suppressible_adaptation(plan: AdaptationPlan) -> bool:
    return plan.modality_suggestion is not None or plan.proactive_adjustment is not None


def _suppression_attempt(
    *,
    request: AdaptationRequest,
    plan: AdaptationPlan,
    reason: str,
) -> SuppressedAdaptationAttempt:
    return SuppressedAdaptationAttempt(
        attempted_type="modality_shift"
        if plan.modality_suggestion is not None
        else "proactive_adjustment",
        reason=reason,
        current_segment_id=request.signals.current_segment_id,
        current_modality=request.signals.current_modality,
        suggested_modality=(
            plan.modality_suggestion.suggested
            if plan.modality_suggestion is not None
            else None
        ),
        confidence=_plan_confidence(plan),
        trigger_signals=_plan_trigger_signals(plan),
    )


def _suppress_plan(
    *,
    plan: AdaptationPlan,
    attempt: SuppressedAdaptationAttempt,
) -> AdaptationPlan:
    return replace(
        plan,
        proactive_adjustment=None,
        modality_suggestion=None,
        suppressed_attempt=attempt,
    )


def _plan_confidence(plan: AdaptationPlan) -> float:
    if plan.modality_suggestion is not None:
        return plan.modality_suggestion.adaptation_confidence
    if plan.proactive_adjustment is not None:
        return plan.proactive_adjustment.confidence
    return 0


def _plan_trigger_signals(plan: AdaptationPlan) -> tuple[TriggerSignal, ...]:
    if plan.modality_suggestion is not None:
        return plan.modality_suggestion.trigger_signals
    if plan.proactive_adjustment is not None:
        return plan.proactive_adjustment.trigger_signals
    return ()


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


def _proactive_adjustment(
    *,
    signals: RuntimeSignals,
    profile: LearnerProfileSnapshot,
) -> ProactiveAdjustment | None:
    evidence = _trigger_signals(signals=signals, profile=profile)
    confidence = _combined_confidence(evidence)
    if not _evidence_allows_adaptation(signals=signals, evidence=evidence):
        return None
    evidence_by_category = _evidence_by_category(evidence)
    if "comprehension" in evidence_by_category and {
        "engagement",
        "performance",
    }.intersection(evidence_by_category):
        return ProactiveAdjustment(
            action="simplify",
            reason="Comprehension has dropped below this session's average.",
            confidence=confidence,
            trigger_signals=evidence,
        )
    if "engagement" in evidence_by_category and "comprehension" in evidence_by_category:
        return ProactiveAdjustment(
            action="slower",
            reason="Multiple signals suggest the current pace may be too high.",
            confidence=confidence,
            trigger_signals=evidence,
        )
    positive_evidence = _positive_trigger_signals(signals)
    if _evidence_allows_adaptation(signals=signals, evidence=positive_evidence):
        return ProactiveAdjustment(
            action="expand",
            reason="Engagement and comprehension are both above the current baseline.",
            confidence=_combined_confidence(positive_evidence),
            trigger_signals=positive_evidence,
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
    trigger_signals = _trigger_signals(signals=signals, profile=profile)
    profile_signal = TriggerSignal(
        category="profile",
        name=f"{candidate}_available",
        confidence=_confidence_rank(_profile_channels(profile)[candidate].confidence),
    )
    trigger_signals = (*trigger_signals, profile_signal)
    if not _evidence_allows_adaptation(signals=signals, evidence=trigger_signals):
        return None
    return ModalitySuggestion(
        suggested=MODALITY_BY_CHANNEL[candidate],
        trigger_reason="combined",
        confidence=_profile_channels(profile)[candidate].confidence,
        adaptation_confidence=_combined_confidence(trigger_signals),
        trigger_signals=trigger_signals,
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


def _trigger_signals(
    *,
    signals: RuntimeSignals,
    profile: LearnerProfileSnapshot,
) -> tuple[TriggerSignal, ...]:
    evidence: list[TriggerSignal] = []
    if (
        signals.comprehension_score is not None
        and signals.session_average_comprehension is not None
    ):
        drop = signals.session_average_comprehension - signals.comprehension_score
        if drop >= 20:
            evidence.append(
                TriggerSignal(
                    category="comprehension",
                    name="comprehension_drop",
                    confidence=min(0.95, 0.60 + (drop / 100)),
                )
            )
    if signals.accuracy_below_baseline:
        evidence.append(
            TriggerSignal(
                category="comprehension",
                name="accuracy_below_baseline",
                confidence=0.72,
            )
        )
    if signals.response_time_below_baseline and (
        signals.accuracy_below_baseline
        or (
            signals.comprehension_score is not None
            and signals.session_average_comprehension is not None
            and signals.session_average_comprehension > signals.comprehension_score
        )
    ):
        evidence.append(
            TriggerSignal(
                category="comprehension",
                name="response_time_with_accuracy_shift",
                confidence=0.64,
            )
        )
    if signals.engagement_below_baseline_seconds >= 180:
        evidence.append(
            TriggerSignal(
                category="engagement",
                name="engagement_below_baseline",
                confidence=0.70,
            )
        )
    if (
        signals.engagement_score is not None
        and signals.engagement_baseline is not None
        and signals.engagement_score <= signals.engagement_baseline - 0.15
    ):
        evidence.append(
            TriggerSignal(
                category="engagement",
                name="engagement_score_drop",
                confidence=0.70,
            )
        )
    if signals.replay_count_on_segment >= 3 and _comprehension_declining(signals):
        evidence.append(
            TriggerSignal(
                category="engagement",
                name="replay_accumulation_with_comprehension_shift",
                confidence=0.68,
            )
        )
    if signals.consecutive_errors >= 3:
        evidence.append(
            TriggerSignal(
                category="performance",
                name="repeated_errors",
                confidence=0.76,
            )
        )
    if profile.working_memory_capacity is not None and profile.working_memory_capacity <= 2:
        evidence.append(
            TriggerSignal(
                category="profile",
                name="working_memory_support_pattern",
                confidence=0.62,
            )
        )
    return tuple(evidence)


def _positive_trigger_signals(signals: RuntimeSignals) -> tuple[TriggerSignal, ...]:
    evidence: list[TriggerSignal] = []
    if (
        signals.engagement_score is not None
        and signals.engagement_baseline is not None
        and signals.engagement_score >= signals.engagement_baseline + 0.2
    ):
        evidence.append(
            TriggerSignal(
                category="engagement",
                name="engagement_above_baseline",
                confidence=0.72,
            )
        )
    if (
        signals.comprehension_score is not None
        and signals.session_average_comprehension is not None
        and signals.comprehension_score >= signals.session_average_comprehension
    ):
        evidence.append(
            TriggerSignal(
                category="comprehension",
                name="comprehension_at_or_above_session_average",
                confidence=0.70,
            )
        )
    if signals.consecutive_errors == 0 and signals.replay_count_on_segment == 0:
        evidence.append(
            TriggerSignal(
                category="performance",
                name="no_current_error_or_replay_pattern",
                confidence=0.66,
            )
        )
    return tuple(evidence)


def _evidence_allows_adaptation(
    *,
    signals: RuntimeSignals,
    evidence: tuple[TriggerSignal, ...],
) -> bool:
    if len(evidence) < MIN_ALIGNED_SIGNAL_COUNT:
        return False
    if len(_evidence_by_category(evidence)) < MIN_ALIGNED_SIGNAL_CATEGORIES:
        return False
    return _combined_confidence(evidence) >= _confidence_threshold(signals)


def _combined_confidence(evidence: tuple[TriggerSignal, ...]) -> float:
    if not evidence:
        return 0
    return round(sum(item.confidence for item in evidence) / len(evidence), 2)


def _evidence_by_category(evidence: tuple[TriggerSignal, ...]) -> set[str]:
    return {item.category for item in evidence}


def _confidence_threshold(signals: RuntimeSignals) -> float:
    if (
        signals.session_modality_shift_count is not None
        and signals.session_modality_shift_count > 0
    ):
        return SUBSEQUENT_ADAPTATION_CONFIDENCE_THRESHOLD
    return FIRST_ADAPTATION_CONFIDENCE_THRESHOLD


def _confidence_rank(confidence: ConfidenceLevel) -> float:
    return {
        ConfidenceLevel.LOW: 0.45,
        ConfidenceLevel.MEDIUM: 0.65,
        ConfidenceLevel.HIGH: 0.85,
    }[confidence]


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
