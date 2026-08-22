from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from nevo.api.auth import PrincipalDependency
from nevo.domain.intelligence.vocabulary import (
    AccommodationType,
    AdaptationMode,
    BreakType,
    ContentModality,
    ContentSegmentType,
    DensityLevel,
    ScaffoldingLevel,
    ScaffoldIntensity,
    ScaffoldOutcome,
)
from nevo.domain.learner_profiles.vocabulary import ConfidenceLevel
from nevo.intelligence.accommodation_service import AccommodationInferenceService
from nevo.intelligence.adaptation import AdaptationEngineService
from nevo.intelligence.entities import (
    AccommodationAnalysis,
    AccommodationSignal,
    AdaptationPlan,
    AdaptationRequest,
    BreakThresholdResult,
    ContentSegment,
    ModalitySuggestion,
    ProactiveAdjustment,
    RuntimeSignals,
    ScaffoldConceptState,
    ScaffoldDecision,
    ScaffoldProblemAttempt,
    ScaffoldProblemLogEntry,
    SegmentAdaptation,
)
from nevo.intelligence.scaffold_service import ScaffoldFadingService

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
    current_segment_elapsed_seconds: int | None = Field(
        default=None,
        alias="currentSegmentElapsedSeconds",
        ge=0,
    )
    seconds_since_last_adaptation: int | None = Field(
        default=None,
        alias="secondsSinceLastAdaptation",
        ge=0,
    )
    session_modality_shift_count: int | None = Field(
        default=None,
        alias="sessionModalityShiftCount",
        ge=0,
    )


class AdaptRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    student_id: UUID | None = Field(default=None, alias="studentId")
    session_id: UUID | None = Field(default=None, alias="sessionId")
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


class AccommodationSignalResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    accommodation: AccommodationType
    frontend_signal: str = Field(alias="frontendSignal")
    evidence: list[str]
    lesson_count: int = Field(alias="lessonCount")

    @classmethod
    def from_signal(cls, signal: AccommodationSignal) -> "AccommodationSignalResponse":
        return cls(
            accommodation=signal.accommodation,
            frontend_signal=signal.frontend_signal,
            evidence=list(signal.evidence),
            lesson_count=signal.lesson_count,
        )


class AccommodationAnalysisResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    student_id: UUID = Field(alias="studentId")
    active_accommodations: list[AccommodationType] = Field(alias="activeAccommodations")
    frontend_signals: list[str] = Field(alias="frontendSignals")
    signals: list[AccommodationSignalResponse]
    source: str
    persisted_as_label: bool = Field(alias="persistedAsLabel")

    @classmethod
    def from_analysis(
        cls,
        analysis: AccommodationAnalysis,
    ) -> "AccommodationAnalysisResponse":
        return cls(
            student_id=analysis.student_id,
            active_accommodations=[
                signal.accommodation for signal in analysis.active
            ],
            frontend_signals=[signal.frontend_signal for signal in analysis.active],
            signals=[
                AccommodationSignalResponse.from_signal(signal)
                for signal in analysis.active
            ],
            source=analysis.source,
            persisted_as_label=False,
        )


class ScaffoldStateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    student_id: UUID = Field(alias="studentId")
    concept_id: UUID = Field(alias="conceptId")
    current_intensity: ScaffoldIntensity = Field(alias="currentIntensity")
    consecutive_correct: int = Field(alias="consecutiveCorrect")
    response_time_improvement_streak: int = Field(
        alias="responseTimeImprovementStreak"
    )
    reduced_hint_streak: int = Field(alias="reducedHintStreak")
    last_response_time_ms: int | None = Field(alias="lastResponseTimeMs")
    last_hint_count: int | None = Field(alias="lastHintCount")

    @classmethod
    def from_state(cls, state: ScaffoldConceptState) -> "ScaffoldStateResponse":
        return cls(
            student_id=state.student_id,
            concept_id=state.concept_id,
            current_intensity=state.current_intensity,
            consecutive_correct=state.consecutive_correct,
            response_time_improvement_streak=state.response_time_improvement_streak,
            reduced_hint_streak=state.reduced_hint_streak,
            last_response_time_ms=state.last_response_time_ms,
            last_hint_count=state.last_hint_count,
        )


class ScaffoldAttemptRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    student_id: UUID = Field(alias="studentId")
    concept_id: UUID = Field(alias="conceptId")
    problem_id: str = Field(alias="problemId", min_length=1, max_length=120)
    response_correct: bool = Field(alias="responseCorrect")
    scaffold_intensity: ScaffoldIntensity | None = Field(
        default=None,
        alias="scaffoldIntensity",
    )
    response_time_ms: int | None = Field(default=None, alias="responseTimeMs", ge=0)
    expected_response_time_ms: int | None = Field(
        default=None,
        alias="expectedResponseTimeMs",
        gt=0,
    )
    hint_count: int = Field(default=0, alias="hintCount", ge=0)


class ScaffoldDecisionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    state: ScaffoldStateResponse
    previous_intensity: ScaffoldIntensity = Field(alias="previousIntensity")
    next_intensity: ScaffoldIntensity = Field(alias="nextIntensity")
    outcome: ScaffoldOutcome
    level_changed: bool = Field(alias="levelChanged")
    change_reason: str | None = Field(alias="changeReason")
    student_message: str = Field(alias="studentMessage")

    @classmethod
    def from_decision(cls, decision: ScaffoldDecision) -> "ScaffoldDecisionResponse":
        return cls(
            state=ScaffoldStateResponse.from_state(decision.state),
            previous_intensity=decision.previous_intensity,
            next_intensity=decision.next_intensity,
            outcome=decision.outcome,
            level_changed=decision.level_changed,
            change_reason=decision.change_reason,
            student_message=decision.student_message,
        )


class ScaffoldLogResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    student_id: UUID = Field(alias="studentId")
    concept_id: UUID = Field(alias="conceptId")
    problem_id: str = Field(alias="problemId")
    scaffold_intensity: ScaffoldIntensity = Field(alias="scaffoldIntensity")
    outcome: ScaffoldOutcome
    response_time_ms: int | None = Field(alias="responseTimeMs")
    expected_response_time_ms: int | None = Field(alias="expectedResponseTimeMs")
    hint_count: int = Field(alias="hintCount")
    next_scaffold_intensity: ScaffoldIntensity = Field(alias="nextScaffoldIntensity")
    level_changed: bool = Field(alias="levelChanged")
    change_reason: str | None = Field(alias="changeReason")

    @classmethod
    def from_log(cls, log: ScaffoldProblemLogEntry) -> "ScaffoldLogResponse":
        return cls(
            student_id=log.student_id,
            concept_id=log.concept_id,
            problem_id=log.problem_id,
            scaffold_intensity=log.scaffold_intensity,
            outcome=log.outcome,
            response_time_ms=log.response_time_ms,
            expected_response_time_ms=log.expected_response_time_ms,
            hint_count=log.hint_count,
            next_scaffold_intensity=log.next_scaffold_intensity,
            level_changed=log.level_changed,
            change_reason=log.change_reason,
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


def get_accommodation_inference_service(
    request: Request,
) -> AccommodationInferenceService:
    service = getattr(request.app.state, "accommodation_inference_service", None)
    if not isinstance(service, AccommodationInferenceService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_unavailable",
                "message": "Accommodation inference is temporarily unavailable.",
            },
        )
    return service


AccommodationInferenceDependency = Annotated[
    AccommodationInferenceService,
    Depends(get_accommodation_inference_service),
]


def get_scaffold_fading_service(request: Request) -> ScaffoldFadingService:
    service = getattr(request.app.state, "scaffold_fading_service", None)
    if not isinstance(service, ScaffoldFadingService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_unavailable",
                "message": "Scaffold fading is temporarily unavailable.",
            },
        )
    return service


ScaffoldFadingDependency = Annotated[
    ScaffoldFadingService,
    Depends(get_scaffold_fading_service),
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
            session_id=payload.session_id,
        ),
        requested_by_user_id=principal.user_id,
    )
    return AdaptResponse.from_plan(plan)


@router.get(
    "/accommodations/{student_id}",
    response_model=AccommodationAnalysisResponse,
)
async def analyse_accommodations(
    student_id: UUID,
    principal: PrincipalDependency,
    service: AccommodationInferenceDependency,
) -> AccommodationAnalysisResponse:
    if principal.role == "student" and student_id != principal.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "student_context_forbidden",
                "message": "Students can view only their own accommodation state.",
            },
        )
    analysis = await service.analyse_student(student_id=student_id)
    return AccommodationAnalysisResponse.from_analysis(analysis)


@router.get(
    "/scaffolds/state/{student_id}/{concept_id}",
    response_model=ScaffoldStateResponse,
)
async def current_scaffold_state(
    student_id: UUID,
    concept_id: UUID,
    principal: PrincipalDependency,
    service: ScaffoldFadingDependency,
) -> ScaffoldStateResponse:
    _ensure_student_or_staff(principal=principal, student_id=student_id)
    state = await service.current_state(student_id=student_id, concept_id=concept_id)
    return ScaffoldStateResponse.from_state(state)


@router.post("/scaffolds/attempt", response_model=ScaffoldDecisionResponse)
async def record_scaffold_attempt(
    payload: ScaffoldAttemptRequest,
    principal: PrincipalDependency,
    service: ScaffoldFadingDependency,
) -> ScaffoldDecisionResponse:
    _ensure_student_or_staff(principal=principal, student_id=payload.student_id)
    decision = await service.record_attempt(
        ScaffoldProblemAttempt(
            student_id=payload.student_id,
            concept_id=payload.concept_id,
            problem_id=payload.problem_id,
            response_correct=payload.response_correct,
            scaffold_intensity=payload.scaffold_intensity,
            response_time_ms=payload.response_time_ms,
            expected_response_time_ms=payload.expected_response_time_ms,
            hint_count=payload.hint_count,
        )
    )
    return ScaffoldDecisionResponse.from_decision(decision)


@router.get(
    "/scaffolds/history/{student_id}",
    response_model=list[ScaffoldLogResponse],
)
async def scaffold_history(
    student_id: UUID,
    principal: PrincipalDependency,
    service: ScaffoldFadingDependency,
    concept_id: UUID | None = None,
    limit: int = 100,
) -> list[ScaffoldLogResponse]:
    if principal.role == "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "scaffold_history_forbidden",
                "message": "Scaffold history is available to staff dashboards.",
            },
        )
    logs = await service.history(
        student_id=student_id,
        concept_id=concept_id,
        limit=min(max(limit, 1), 200),
    )
    return [ScaffoldLogResponse.from_log(log) for log in logs]


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


def _ensure_student_or_staff(*, principal, student_id: UUID) -> None:
    if principal.role == "student" and student_id != principal.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "student_context_forbidden",
                "message": "Students can use only their own scaffold state.",
            },
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
        current_segment_elapsed_seconds=signals.current_segment_elapsed_seconds,
        seconds_since_last_adaptation=signals.seconds_since_last_adaptation,
        session_modality_shift_count=signals.session_modality_shift_count,
    )
