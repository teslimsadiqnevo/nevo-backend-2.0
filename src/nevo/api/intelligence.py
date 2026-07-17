from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from nevo.api.auth import PrincipalDependency
from nevo.domain.intelligence.vocabulary import (
    AdaptationMode,
    BreakType,
    ContentModality,
    ContentSegmentType,
    DensityLevel,
    ScaffoldingLevel,
)
from nevo.domain.learner_profiles.vocabulary import ConfidenceLevel
from nevo.intelligence.adaptation import AdaptationEngineService
from nevo.intelligence.entities import (
    AdaptationPlan,
    AdaptationRequest,
    BreakThresholdResult,
    ContentSegment,
    ModalitySuggestion,
    ProactiveAdjustment,
    RuntimeSignals,
    SegmentAdaptation,
)

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


class ContentSegmentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(min_length=1, max_length=120)
    segment_type: ContentSegmentType = Field(alias="segmentType")
    available_modalities: list[ContentModality] = Field(
        alias="availableModalities",
        min_length=1,
    )
    concept_id: str | None = Field(default=None, alias="conceptId", max_length=120)
    estimated_minutes: float | None = Field(
        default=None,
        alias="estimatedMinutes",
        gt=0,
    )
    passive: bool = False
    title: str | None = Field(default=None, max_length=255)


class RuntimeSignalsRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    current_segment_id: str | None = Field(default=None, alias="currentSegmentId")
    current_modality: ContentModality | None = Field(
        default=None,
        alias="currentModality",
    )
    available_modalities: list[ContentModality] = Field(
        default_factory=list,
        alias="availableModalities",
    )
    continuous_minutes: float = Field(default=0, alias="continuousMinutes", ge=0)
    engagement_score: float | None = Field(
        default=None,
        alias="engagementScore",
        ge=0,
        le=1,
    )
    engagement_baseline: float | None = Field(
        default=None,
        alias="engagementBaseline",
        ge=0,
        le=1,
    )
    engagement_below_baseline_seconds: int = Field(
        default=0,
        alias="engagementBelowBaselineSeconds",
        ge=0,
    )
    comprehension_score: float | None = Field(
        default=None,
        alias="comprehensionScore",
        ge=0,
        le=100,
    )
    session_average_comprehension: float | None = Field(
        default=None,
        alias="sessionAverageComprehension",
        ge=0,
        le=100,
    )
    consecutive_errors: int = Field(default=0, alias="consecutiveErrors", ge=0)
    replay_count_on_segment: int = Field(
        default=0,
        alias="replayCountOnSegment",
        ge=0,
    )
    same_segment_suggestion_shown: bool = Field(
        default=False,
        alias="sameSegmentSuggestionShown",
    )
    segments_since_last_suggestion: int | None = Field(
        default=None,
        alias="segmentsSinceLastSuggestion",
        ge=0,
    )
    declined_modalities: list[ContentModality] = Field(
        default_factory=list,
        alias="declinedModalities",
    )
    session_decline_count: int = Field(default=0, alias="sessionDeclineCount", ge=0)
    accuracy_below_baseline: bool = Field(
        default=False,
        alias="accuracyBelowBaseline",
    )
    response_time_below_baseline: bool = Field(
        default=False,
        alias="responseTimeBelowBaseline",
    )
    midpoint_reached: bool = Field(default=False, alias="midpointReached")


class AdaptRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    student_id: UUID | None = Field(default=None, alias="studentId")
    lesson_id: UUID = Field(alias="lessonId")
    mode: AdaptationMode = AdaptationMode.LESSON_LOAD
    segments: list[ContentSegmentRequest] = Field(min_length=1, max_length=500)
    signals: RuntimeSignalsRequest = Field(default_factory=RuntimeSignalsRequest)


class BreakSuggestionResponse(BaseModel):
    triggered_thresholds: list[str]
    severity: str
    break_type: BreakType | None
    reason: str | None

    @classmethod
    def from_result(cls, result: BreakThresholdResult) -> "BreakSuggestionResponse":
        return cls(
            triggered_thresholds=list(result.triggered_thresholds),
            severity=result.severity,
            break_type=result.break_type,
            reason=result.reason,
        )


class SegmentAdaptationResponse(BaseModel):
    segment_id: str
    modality: ContentModality
    density: DensityLevel
    scaffolding: ScaffoldingLevel
    priority: int

    @classmethod
    def from_segment(
        cls,
        segment: SegmentAdaptation,
    ) -> "SegmentAdaptationResponse":
        return cls(
            segment_id=segment.segment_id,
            modality=segment.modality,
            density=segment.density,
            scaffolding=segment.scaffolding,
            priority=segment.priority,
        )


class ProactiveAdjustmentResponse(BaseModel):
    action: str
    reason: str

    @classmethod
    def from_adjustment(
        cls,
        adjustment: ProactiveAdjustment,
    ) -> "ProactiveAdjustmentResponse":
        return cls(action=adjustment.action, reason=adjustment.reason)


class ModalitySuggestionResponse(BaseModel):
    suggested: ContentModality
    trigger_reason: str
    confidence: ConfidenceLevel

    @classmethod
    def from_suggestion(
        cls,
        suggestion: ModalitySuggestion,
    ) -> "ModalitySuggestionResponse":
        return cls(
            suggested=suggestion.suggested,
            trigger_reason=suggestion.trigger_reason,
            confidence=suggestion.confidence,
        )


class AdaptResponse(BaseModel):
    lesson_id: UUID
    source: str
    segments: list[SegmentAdaptationResponse]
    break_suggestion: BreakSuggestionResponse
    proactive_adjustment: ProactiveAdjustmentResponse | None
    modality_suggestion: ModalitySuggestionResponse | None

    @classmethod
    def from_plan(cls, plan: AdaptationPlan) -> "AdaptResponse":
        return cls(
            lesson_id=plan.lesson_id,
            source=plan.source,
            segments=[
                SegmentAdaptationResponse.from_segment(segment)
                for segment in plan.segments
            ],
            break_suggestion=BreakSuggestionResponse.from_result(
                plan.break_suggestion
            ),
            proactive_adjustment=(
                ProactiveAdjustmentResponse.from_adjustment(
                    plan.proactive_adjustment
                )
                if plan.proactive_adjustment is not None
                else None
            ),
            modality_suggestion=(
                ModalitySuggestionResponse.from_suggestion(plan.modality_suggestion)
                if plan.modality_suggestion is not None
                else None
            ),
        )


def get_adaptation_engine(request: Request) -> AdaptationEngineService:
    service = getattr(request.app.state, "adaptation_engine_service", None)
    if not isinstance(service, AdaptationEngineService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_unavailable",
                "message": "Adaptation is temporarily unavailable.",
            },
        )
    return service


AdaptationEngineDependency = Annotated[
    AdaptationEngineService,
    Depends(get_adaptation_engine),
]


@router.post("/adapt", response_model=AdaptResponse)
async def adapt_lesson(
    payload: AdaptRequest,
    principal: PrincipalDependency,
    service: AdaptationEngineDependency,
) -> AdaptResponse:
    student_id = payload.student_id or principal.user_id
    if student_id != principal.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "student_context_forbidden",
                "message": "Adaptation requests must use the current student.",
            },
        )
    plan = await service.adapt(
        request=AdaptationRequest(
            student_id=student_id,
            lesson_id=payload.lesson_id,
            mode=payload.mode,
            segments=tuple(_segment_from_request(segment) for segment in payload.segments),
            signals=_signals_from_request(payload.signals),
        ),
        requested_by_user_id=principal.user_id,
    )
    return AdaptResponse.from_plan(plan)


def _segment_from_request(segment: ContentSegmentRequest) -> ContentSegment:
    return ContentSegment(
        id=segment.id,
        segment_type=segment.segment_type,
        available_modalities=tuple(segment.available_modalities),
        concept_id=segment.concept_id,
        estimated_minutes=segment.estimated_minutes,
        passive=segment.passive,
        title=segment.title,
    )


def _signals_from_request(signals: RuntimeSignalsRequest) -> RuntimeSignals:
    return RuntimeSignals(
        current_segment_id=signals.current_segment_id,
        current_modality=signals.current_modality,
        available_modalities=tuple(signals.available_modalities),
        continuous_minutes=signals.continuous_minutes,
        engagement_score=signals.engagement_score,
        engagement_baseline=signals.engagement_baseline,
        engagement_below_baseline_seconds=(
            signals.engagement_below_baseline_seconds
        ),
        comprehension_score=signals.comprehension_score,
        session_average_comprehension=signals.session_average_comprehension,
        consecutive_errors=signals.consecutive_errors,
        replay_count_on_segment=signals.replay_count_on_segment,
        same_segment_suggestion_shown=signals.same_segment_suggestion_shown,
        segments_since_last_suggestion=signals.segments_since_last_suggestion,
        declined_modalities=tuple(signals.declined_modalities),
        session_decline_count=signals.session_decline_count,
        accuracy_below_baseline=signals.accuracy_below_baseline,
        response_time_below_baseline=signals.response_time_below_baseline,
        midpoint_reached=signals.midpoint_reached,
    )
