from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from sqlalchemy import select

from nevo.api.auth import PrincipalDependency
from nevo.api.casing import CAMEL_CONFIG
from nevo.api.consent import StudentLearningConsent
from nevo.api.dependencies import DatabaseSession
from nevo.api.lesson_contracts import GuidedStepPrompt
from nevo.db.models.account import User
from nevo.db.models.content import LessonSegment
from nevo.db.models.product import LessonQuestionAttempt
from nevo.db.models.signal_event import AdaptationDecision, LessonSession
from nevo.domain.intelligence.vocabulary import (
    AccommodationType,
    AdaptationMode,
    BreakSeverity,
    BreakThreshold,
    BreakType,
    ContentModality,
    ContentSegmentType,
    DensityLevel,
    ProactiveAction,
    ScaffoldingLevel,
    ScaffoldIntensity,
    ScaffoldOutcome,
)
from nevo.domain.learner_profiles.vocabulary import ConfidenceLevel
from nevo.intelligence.accommodation_service import AccommodationInferenceService
from nevo.intelligence.adaptation import AdaptationEngineService
from nevo.intelligence.comprehension import ComprehensionGate, gate_for_position
from nevo.intelligence.entities import (
    AccommodationAnalysis,
    AccommodationSignal,
    AdaptationPlan,
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
    TriggerSignal,
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
    #: Which parse-time rewrites this segment carries, from the lesson's
    #: ``depthVariants``. Omit it and the engine behaves as it always has;
    #: send it and the engine will not propose a simplify or an expand that
    #: this segment has no text for.
    available_depths: list[Literal["simplified", "expanded"]] | None = Field(
        default=None,
        alias="availableDepths",
    )
    title: str | None = Field(default=None, max_length=255)


class RuntimeSignalsRequest(BaseModel):
    frustration_detected: bool = Field(
        default=False,
        alias="frustrationDetected",
        description=(
            "Optional device-derived transient cue for a break; never send raw touch data."
        ),
    )
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
        deprecated=True,
        description="Ignored compatibility input; the server derives this from persisted events.",
        ge=0,
        le=1,
    )
    engagement_baseline: float | None = Field(
        default=None,
        alias="engagementBaseline",
        deprecated=True,
        description="Ignored compatibility input; personal references are derived server-side.",
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
        deprecated=True,
        description="Ignored compatibility input; the server uses saved, marked answers.",
        ge=0,
        le=100,
    )
    session_average_comprehension: float | None = Field(
        default=None,
        alias="sessionAverageComprehension",
        deprecated=True,
        description=(
            "Ignored compatibility input; the server derives the reference from marked answers."
        ),
        ge=0,
        le=100,
    )
    consecutive_errors: int = Field(
        default=0,
        alias="consecutiveErrors",
        ge=0,
        description=(
            "Wrong answers in a row anywhere in this lesson, reset by a right "
            "one. A running streak, not per step - which is what you are "
            "already sending, so nothing changes. Two in a row is what makes "
            "the engine offer a hint."
        ),
    )
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
        description=(
            "Seconds since the last adaptation was *applied* on screen - not "
            "since it was decided, and not since the last request. Null when "
            "none has been applied this session. It feeds the cooldown that "
            "stops the lesson rearranging itself twice in a minute, so "
            "counting from the wrong moment makes the engine either too eager "
            "or deaf."
        ),
    )
    session_modality_shift_count: int | None = Field(
        default=None,
        alias="sessionModalityShiftCount",
        ge=0,
        description=(
            "Modality changes so far in the whole session, not within the "
            "current segment, and however they came about - offered, accepted "
            "or switched by the child. It caps how often one session may be "
            "rearranged, and a per-segment count would reset that cap at "
            "every segment."
        ),
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
    model_config = CAMEL_CONFIG

    #: Named, so a client can see the five without asking. Empty when nothing
    #: fired, which is the common case.
    triggered_thresholds: list[BreakThreshold]
    severity: BreakSeverity
    break_type: BreakType | None
    reason: str | None
    suppressed_reason: Literal["break_declined", "break_in_progress"] | None = None
    retry_at: datetime | None = None
    always_available: Literal[True] = True
    offer_persistent: bool = False

    @classmethod
    def from_result(cls, result: BreakThresholdResult) -> "BreakSuggestionResponse":
        return cls(
            triggered_thresholds=list(result.triggered_thresholds),
            severity=result.severity,
            break_type=result.break_type,
            reason=(
                "You can stop for today and come back to this part."
                if result.break_type == BreakType.STOP_FOR_DAY
                else "You can pause here and return to this part."
                if result.break_type is not None
                else None
            ),
        )


class SegmentAdaptationResponse(BaseModel):
    model_config = CAMEL_CONFIG

    segment_id: str
    modality: ContentModality
    density: DensityLevel
    scaffolding: ScaffoldingLevel
    priority: int
    available_formats: list[ContentModality] = Field(default_factory=list)
    recommended_format: ContentModality | None = None
    chosen_depth: Literal["original", "simplified", "expanded"] | None = None
    slower: bool | None = None
    density_scope: Literal["segment"] = Field(
        default="segment", description="Density applies only to this segment until replaced."
    )

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


class GuidedPrompt(BaseModel):
    """One question in the socratic panel, and how to answer it."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    prompt: str
    #: Where the panel offers choices. Empty means the child answers in their
    #: own words, which stay on the device - only the id and the option, or
    #: the length of what they wrote, are ever sent back.
    options: list[str] = Field(default_factory=list)


class GuidedAnswerRequest(BaseModel):
    """A structured choice/construction, marked against a stored guided-step key.

    outcome and responseLength are legacy metadata, never correctness evidence.
    """

    model_config = ConfigDict(populate_by_name=True)

    student_id: UUID = Field(alias="studentId")
    session_id: UUID | None = Field(default=None, alias="sessionId")
    prompt_id: str = Field(alias="promptId", max_length=160)
    question_id: str | None = Field(default=None, alias="questionId", max_length=160)
    answer: JsonValue = None
    concept_id: UUID | None = Field(default=None, alias="conceptId")
    option: str | None = Field(default=None, max_length=200)
    response_length: int | None = Field(default=None, alias="responseLength", ge=0, le=10_000)
    #: Whether the child moved on after this question, as the panel observed
    #: it: they continued, they asked again, or they gave up on it.
    outcome: Literal["moved_on", "asked_again", "abandoned"] = "moved_on"


class GuidedAnswerResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    recorded: bool = True
    prompt_id: str = Field(alias="promptId")
    correct: bool | None = None
    panel_complete: bool = Field(default=False, alias="panelComplete")
    can_advance: Literal[False] = Field(default=False, alias="canAdvance")
    retry_check: bool = Field(default=False, alias="retryCheck")
    question_id: str | None = Field(default=None, alias="questionId")
    prompt: GuidedStepPrompt | None = None
    feedback: str | None = None


class ProactiveAdjustmentResponse(BaseModel):
    model_config = CAMEL_CONFIG

    action: ProactiveAction
    #: Why the engine decided this. The reasoning frame, for a teacher or an
    #: audit - not copy to put in front of a child.
    reason: str
    confidence: float
    trigger_signals: list["TriggerSignalResponse"]
    #: The hint itself, when the action is offer_hint. Sent because reason
    #: cannot stand in for it: reason explains the decision, and showing a
    #: learner why the system thinks they are struggling is the thing the
    #: no-labels position exists to prevent.
    hint: str | None = None
    #: What the socratic panel walks through, in order, when the action is
    #: show_socratic_panel. Questions that lead a learner to the answer rather
    #: than giving it.
    guided_questions: list[str] = Field(default_factory=list, alias="guidedQuestions")
    #: The same questions, each with an id, so the child's answer has
    #: somewhere to go. A bare list of strings could be rendered and not
    #: replied to, which meant the guided dialogue could not be built at all.
    #: Derived from guidedQuestions, which stays for now. Ask B19.
    guided_prompts: list["GuidedPrompt"] = Field(default_factory=list, alias="guidedPrompts")
    #: The segment this is about. Always the one the request named, so a
    #: client can stop inferring it - and if the engine ever means a
    #: different one, it will say so here rather than silently. Ask B46.
    segment_id: str | None = Field(default=None, alias="segmentId")
    suggested_modality: ContentModality | None = Field(default=None, alias="suggestedModality")
    scaffold_level: ScaffoldingLevel | None = Field(default=None, alias="scaffoldLevel")
    guided_steps: list[GuidedStepPrompt] = Field(default_factory=list, alias="guidedSteps")
    requires_choice: bool = Field(default=False, alias="requiresChoice")

    @model_validator(mode="after")
    def _carry_what_the_action_needs(self) -> "ProactiveAdjustmentResponse":
        """An action whose payload is missing cannot be rendered.

        Better to refuse it here than to send a client an instruction to show
        a hint and nothing to show.
        """

        if self.action is ProactiveAction.OFFER_HINT and not (self.hint or "").strip():
            raise ValueError("offer_hint carries no hint text")
        if self.action is ProactiveAction.SHOW_SOCRATIC_PANEL and not (
            self.guided_questions or self.guided_steps
        ):
            raise ValueError("show_socratic_panel carries no questions")
        return self

    @classmethod
    def from_adjustment(
        cls,
        adjustment: ProactiveAdjustment,
        segment_id: str | None = None,
    ) -> "ProactiveAdjustmentResponse":
        return cls(
            action=ProactiveAction(adjustment.action),
            reason={
                "simplify": "Here is another way to read this.",
                "expand": "Here is more about the same idea.",
                "slower": "Let's take this one piece at a time.",
                "offer_hint": "Here is something to try.",
                "show_socratic_panel": "Let's work through this together.",
            }[adjustment.action],
            hint=adjustment.hint,
            guidedQuestions=list(adjustment.guided_questions),
            guidedPrompts=[
                GuidedPrompt(id=f"gq-{index}", prompt=question)
                for index, question in enumerate(adjustment.guided_questions)
            ],
            segmentId=segment_id or adjustment.segment_id,
            confidence=adjustment.confidence,
            trigger_signals=[
                TriggerSignalResponse.from_signal(signal) for signal in adjustment.trigger_signals
            ],
        )


class TriggerSignalResponse(BaseModel):
    category: str
    name: str
    confidence: float

    @classmethod
    def from_signal(cls, signal: TriggerSignal) -> "TriggerSignalResponse":
        return cls(
            category=signal.category,
            name=signal.name,
            confidence=signal.confidence,
        )


class ModalitySuggestionResponse(BaseModel):
    model_config = CAMEL_CONFIG

    suggested: ContentModality
    trigger_reason: str
    confidence: ConfidenceLevel
    adaptation_confidence: float
    trigger_signals: list[TriggerSignalResponse]

    @classmethod
    def from_suggestion(
        cls,
        suggestion: ModalitySuggestion,
    ) -> "ModalitySuggestionResponse":
        return cls(
            suggested=suggestion.suggested,
            trigger_reason=suggestion.trigger_reason,
            confidence=suggestion.confidence,
            adaptation_confidence=suggestion.adaptation_confidence,
            trigger_signals=[
                TriggerSignalResponse.from_signal(signal) for signal in suggestion.trigger_signals
            ],
        )


class AdaptResponse(BaseModel):
    model_config = CAMEL_CONFIG

    lesson_id: UUID
    source: str
    segments: list[SegmentAdaptationResponse]
    break_suggestion: BreakSuggestionResponse
    proactive_adjustment: ProactiveAdjustmentResponse | None
    modality_suggestion: ModalitySuggestionResponse | None = Field(
        default=None,
        deprecated=True,
        description=(
            "Retired separate pill. Use each segment's recommendedFormat in its format control."
        ),
    )
    suppressed_attempt: "SuppressedAdaptationResponse | None" = None
    decision_id: UUID | None = None
    adjustment_disposition: Literal["apply", "retain", "clear"] = Field(
        default="clear",
        description="retain never dismisses active question help, including during cooldown.",
    )
    cooldown_until: datetime | None = None
    support_grace_until: datetime | None = None
    comprehension_gate: ComprehensionGate | None = None

    @classmethod
    def from_plan(cls, plan: AdaptationPlan) -> "AdaptResponse":
        return cls(
            lesson_id=plan.lesson_id,
            source=plan.source,
            segments=[SegmentAdaptationResponse.from_segment(segment) for segment in plan.segments],
            break_suggestion=BreakSuggestionResponse.from_result(plan.break_suggestion),
            proactive_adjustment=(
                ProactiveAdjustmentResponse.from_adjustment(
                    plan.proactive_adjustment,
                    segment_id=plan.proactive_adjustment.segment_id,
                )
                if plan.proactive_adjustment is not None
                else None
            ),
            modality_suggestion=(
                ModalitySuggestionResponse.from_suggestion(plan.modality_suggestion)
                if plan.modality_suggestion is not None
                else None
            ),
            suppressed_attempt=(
                SuppressedAdaptationResponse(
                    reason=plan.suppressed_attempt.reason,
                    attempted_type=plan.suppressed_attempt.attempted_type,
                    confidence=plan.suppressed_attempt.confidence,
                    trigger_signals=[
                        TriggerSignalResponse.from_signal(item)
                        for item in plan.suppressed_attempt.trigger_signals
                    ],
                )
                if plan.suppressed_attempt
                else None
            ),
        )


class SuppressedAdaptationResponse(BaseModel):
    model_config = CAMEL_CONFIG

    reason: str
    attempted_type: str
    confidence: float
    trigger_signals: list[TriggerSignalResponse]


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
    #: Always false, and that is the point: it is an attestation, not a
    #: computed value. Nevo works out what support a learner needs from what
    #: they did, and writes none of it down as a label about the child - so
    #: this field says, on every response, that nothing here became one.
    #: Counsel asks whether an analysis like this is ever persisted as a
    #: characteristic; the answer is on the wire rather than in a document.
    persisted_as_label: Literal[False] = Field(
        default=False,
        alias="persistedAsLabel",
        description=(
            "Always false. Nevo derives accommodations from observed behaviour "
            "and never stores the result as a label attached to the learner. "
            "Sent on every response so the guarantee is visible to a client "
            "and an auditor rather than asserted elsewhere."
        ),
    )

    @classmethod
    def from_analysis(
        cls,
        analysis: AccommodationAnalysis,
    ) -> "AccommodationAnalysisResponse":
        return cls(
            student_id=analysis.student_id,
            active_accommodations=[signal.accommodation for signal in analysis.active],
            frontend_signals=[signal.frontend_signal for signal in analysis.active],
            signals=[AccommodationSignalResponse.from_signal(signal) for signal in analysis.active],
            source=analysis.source,
        )


class ScaffoldStateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    student_id: UUID = Field(alias="studentId")
    concept_id: UUID = Field(alias="conceptId")
    current_intensity: ScaffoldIntensity = Field(alias="currentIntensity")
    consecutive_correct: int = Field(alias="consecutiveCorrect")
    response_time_improvement_streak: int = Field(alias="responseTimeImprovementStreak")
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
    answer_attempt_id: UUID | None = Field(default=None, alias="answerAttemptId")
    #: Where the problem came from, so the server can find the answer rather
    #: than being told the mark. Send these and leave responseCorrect out.
    #: Ask B27.
    lesson_id: UUID | None = Field(default=None, alias="lessonId")
    segment_id: UUID | None = Field(default=None, alias="segmentId")
    #: What the child actually picked or typed. Marked here against the stored
    #: calculation, which is where the answer lives.
    answer: str | None = Field(default=None, max_length=400)
    #: Legacy staff recording only. Student requests require answerAttemptId
    #: and cannot use this verdict or choose their scaffold intensity.
    response_correct: bool | None = Field(default=None, alias="responseCorrect")

    @model_validator(mode="after")
    def _something_to_mark(self) -> "ScaffoldAttemptRequest":
        if self.answer is None and self.response_correct is None and self.answer_attempt_id is None:
            raise ValueError("Send answer with lessonId and segmentId, or responseCorrect.")
        return self

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
    session: DatabaseSession,
    consent: StudentLearningConsent = None,
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
    from nevo.intelligence.adaptation_context import prepare_adaptation

    context = await prepare_adaptation(
        session, principal, payload, _signals_from_request(payload.signals)
    )
    plan = await service.adapt(
        request=context,
        requested_by_user_id=principal.user_id,
    )
    response = AdaptResponse.from_plan(plan)
    sitting = (
        await session.get(
            LessonSession, context.session_id, populate_existing=True, with_for_update=True
        )
        if context.session_id
        else None
    )
    if sitting is not None and sitting.ended_at is not None:
        raise HTTPException(
            409,
            detail={
                "code": "lesson_session_required",
                "message": "Open the lesson before continuing.",
            },
        )
    delivery = dict(sitting.delivery_state or {}) if sitting else {}
    recommendations = dict(delivery.get("recommendations") or {})
    current_row = None
    rows = list(
        await session.scalars(
            select(LessonSegment).where(LessonSegment.lesson_id == payload.lesson_id)
        )
    )
    by_key = {key: row for row in rows for key in (str(row.id), row.segment_key)}
    for item in response.segments:
        row = by_key.get(item.segment_id)
        if row is None:
            raise HTTPException(409, detail={"code": "lesson_content_changed"})
        if context.signals.current_segment_id in {str(row.id), row.segment_key}:
            current_row = row
        from nevo.api.lesson_contracts import student_modalities
        from nevo.intelligence.delivery_preferences import segment_choice

        item.available_formats = [ContentModality(value) for value in student_modalities(row)]
        choice = segment_choice(sitting, row)
        if choice.get("modality") in item.available_formats:
            item.modality = ContentModality(choice["modality"])
        item.chosen_depth, item.slower = choice.get("depth"), choice.get("slower")
        adjustment = response.proactive_adjustment
        if adjustment and context.signals.current_segment_id in {str(row.id), row.segment_key}:
            if (
                choice.get("depth") is not None and adjustment.action in {"simplify", "expand"}
            ) or (choice.get("slower") is not None and adjustment.action == "slower"):
                response.proactive_adjustment = None
        if plan.modality_suggestion and context.signals.current_segment_id in {
            str(row.id),
            row.segment_key,
        }:
            candidate = plan.modality_suggestion.suggested
            if candidate in item.available_formats:
                recommendations[str(row.id)] = candidate.value
        elif context.signals.current_segment_id in {str(row.id), row.segment_key}:
            recommendations.pop(str(row.id), None)
        candidate = recommendations.get(str(row.id))
        item.recommended_format = (
            ContentModality(candidate) if candidate in item.available_formats else None
        )
    response.support_grace_until = context.signals.support_grace_until
    now = datetime.now(UTC)
    declined = context.signals.break_declined_seconds_ago
    if declined is not None and declined < 120:
        response.break_suggestion.suppressed_reason = "break_declined"
        response.break_suggestion.retry_at = now + timedelta(seconds=120 - declined)
    if context.signals.break_in_progress:
        response.break_suggestion.suppressed_reason = "break_in_progress"
        response.break_suggestion.retry_at = None
    if response.suppressed_attempt and response.suppressed_attempt.reason == "adaptation_cooldown":
        response.adjustment_disposition = "retain"
        elapsed = context.signals.seconds_since_last_adaptation
        if elapsed is not None:
            response.cooldown_until = now + timedelta(seconds=max(0, 120 - elapsed))
    latest = (
        await session.scalar(
            select(LessonQuestionAttempt)
            .where(
                LessonQuestionAttempt.session_id == sitting.id,
                LessonQuestionAttempt.segment_id == current_row.id,
            )
            .order_by(LessonQuestionAttempt.submitted_at.desc())
            .limit(1)
        )
        if sitting and current_row
        else None
    )
    if latest and latest.correct is False and current_row and sitting:
        previous = (delivery.get("reteaching") or {}).get(str(current_row.id)) or {}
        if previous.get("questionId") != latest.question_id:
            from nevo.intelligence.comprehension import note_attempt

            await note_attempt(session, sitting, current_row, latest)
            delivery = dict(sitting.delivery_state or {})
    active = delivery.get("activeSupport") or {}
    from nevo.intelligence.question_support import two_miss_hint

    question_attempts = (
        list(
            await session.scalars(
                select(LessonQuestionAttempt)
                .where(
                    LessonQuestionAttempt.session_id == sitting.id,
                    LessonQuestionAttempt.question_id == latest.question_id,
                    LessonQuestionAttempt.correct.is_not(None),
                )
                .order_by(LessonQuestionAttempt.attempt_number.desc())
                .limit(2)
            )
        )
        if sitting and latest and latest.correct is False
        else []
    )
    authored_hint = two_miss_hint(latest, question_attempts)
    same_question = bool(
        latest
        and current_row
        and active.get("segmentId") == str(current_row.id)
        and active.get("questionId") == latest.question_id
    )
    active_action = (active.get("adjustment") or {}).get("action") if same_question else None
    question_hint = False
    if active_action == "show_socratic_panel":
        response.proactive_adjustment = None
    elif authored_hint:
        if active_action == "offer_hint":
            # Reuse the existing offer/decision instead of issuing another hint on every poll.
            if not response.proactive_adjustment or (
                response.proactive_adjustment.action != ProactiveAction.SHOW_SOCRATIC_PANEL
            ):
                response.proactive_adjustment = None
        elif (
            response.proactive_adjustment is None
            or (response.proactive_adjustment.action != ProactiveAction.SHOW_SOCRATIC_PANEL)
            or latest.question_id not in delivery.get("hintedQuestions", [])
        ):
            response.proactive_adjustment = ProactiveAdjustmentResponse(
                action=ProactiveAction.OFFER_HINT,
                reason="Two marked misses on this question.",
                confidence=1.0,
                trigger_signals=[
                    TriggerSignalResponse(
                        category="question_support",
                        name="two_marked_misses",
                        confidence=1.0,
                    )
                ],
                hint=authored_hint,
                segment_id=str(current_row.id),
            )
            question_hint = True
    if (
        latest is not None
        and latest.correct is not False
        and response.proactive_adjustment is not None
        and response.proactive_adjustment.action
        in {ProactiveAction.OFFER_HINT, ProactiveAction.SHOW_SOCRATIC_PANEL}
    ):
        response.proactive_adjustment = None
    unresolved = (
        current_row is not None
        and latest is not None
        and latest.correct is False
        and active.get("segmentId") == str(current_row.id)
        and active.get("questionId") == latest.question_id
    )
    if response.proactive_adjustment is not None:
        response.adjustment_disposition = "apply"
    elif unresolved and active.get("adjustment"):
        response.proactive_adjustment = ProactiveAdjustmentResponse.model_validate(
            active["adjustment"]
        )
        response.decision_id = UUID(active["decisionId"]) if active.get("decisionId") else None
        response.adjustment_disposition = "retain"
    elif not unresolved:
        delivery.pop("activeSupport", None)
        if active or (latest is not None and latest.correct is not False):
            response.adjustment_disposition = "clear"
        elif (
            latest is not None
            and latest.correct is False
            and response.support_grace_until is not None
            and now >= response.support_grace_until
        ):
            # A direct attempt hand-off may be on screen without an engine-issued decision.
            response.adjustment_disposition = "retain"
    # SCRUM-272 replaces the separate pill with the recommendation in the control.
    if sitting and current_row:
        response.comprehension_gate = await gate_for_position(
            session, sitting, current_row.sequence_order
        )
        teaching = response.comprehension_gate.reteaching
        if latest and latest.correct is False and teaching:
            route = teaching.recommended_route
            actions = {
                "format": "offer_modality_shift",
                "simplify": "simplify",
                "simpler_presentation": "rechunk",
                "slower": "slower",
                "rechunk": "rechunk",
                "panel": "show_socratic_panel",
                "calculation_scaffold": ProactiveAction.CALCULATION_SCAFFOLD,
            }
            from nevo.intelligence.guided_panel import public_prompt

            guided_steps = latest.question_snapshot.get("guidedSteps", [])
            guided_questions = latest.question_snapshot.get("guidedQuestions", [])
            steps = [public_prompt(step) for step in guided_steps]
            response.proactive_adjustment = ProactiveAdjustmentResponse(
                action=ProactiveAction(actions[route.action]),
                reason=route.label,
                confidence=1.0,
                trigger_signals=[
                    TriggerSignalResponse(
                        category="question_support", name="server_marked_miss", confidence=1.0
                    )
                ],
                segment_id=str(current_row.id),
                suggested_modality=route.format,
                scaffold_level=(
                    ScaffoldingLevel.STRONG
                    if route.action == "calculation_scaffold"
                    else None
                ),
                requires_choice=route.action in {"format", "simplify"},
                guided_questions=(
                    [str(question) for question in guided_questions if isinstance(question, str)]
                    if route.action == "panel"
                    else []
                ),
                guided_steps=steps if route.action == "panel" else [],
                hint=teaching.hint,
            )
            # A response to a known wrong answer is not a profile inference and
            # must not wait behind adaptation confidence/dwell/cooldown limits.
            response.suppressed_attempt = None
            response.cooldown_until = None
            response.support_grace_until = None
            response.adjustment_disposition = "apply"
            question_hint = False
            if same_question and active.get("attemptId") == str(latest.id):
                response.adjustment_disposition = "retain"
                response.decision_id = (
                    UUID(active["decisionId"]) if active.get("decisionId") else None
                )
            if route.format:
                recommendations[str(current_row.id)] = route.format
                for item in response.segments:
                    if item.segment_id in {str(current_row.id), current_row.segment_key}:
                        item.recommended_format = ContentModality(route.format)
        # Keep an offer reachable after its first appearance. Declining can
        # suppress a repeated interruption but never removes the break control.
        previous_offer = delivery.get("breakOffer")
        declined_seconds = context.signals.break_declined_seconds_ago
        offered_at = delivery.get("breakOfferAt")
        if previous_offer and declined_seconds is not None and (
            not offered_at
            or now - timedelta(seconds=declined_seconds) >= datetime.fromisoformat(offered_at)
        ):
            previous_offer = None
            delivery.pop("breakOffer", None)
            delivery.pop("breakOfferAt", None)
        if context.signals.break_in_progress or (
            context.signals.break_declined_seconds_ago is not None
            and context.signals.break_declined_seconds_ago < 120
        ):
            delivery.pop("breakOffer", None)
            delivery.pop("breakOfferAt", None)
        elif response.break_suggestion.break_type is not None:
            response.break_suggestion.offer_persistent = True
            delivery["breakOffer"] = response.break_suggestion.model_dump(
                mode="json", by_alias=True
            )
            # Persist the offered action, not an affective-state label/cue.
            delivery["breakOffer"]["triggeredThresholds"] = []
            delivery["breakOfferAt"] = now.isoformat()
        elif previous_offer:
            response.break_suggestion = BreakSuggestionResponse.model_validate(previous_offer)
            response.break_suggestion.offer_persistent = True
    response.modality_suggestion = None
    action = response.proactive_adjustment
    suggestion = plan.modality_suggestion
    if question_hint and context.session_id:
        response.decision_id = uuid4()
        session.add(
            AdaptationDecision(
                id=response.decision_id,
                student_id=context.student_id,
                session_id=context.session_id,
                lesson_id=context.lesson_id,
                segment_id=str(current_row.id),
                action="offer_hint",
                confidence=1.0,
                trigger_signals=[
                    {"category": "question_support", "name": "two_marked_misses", "confidence": 1.0}
                ],
            )
        )
    elif (
        context.session_id
        and (action is not None or suggestion is not None)
        and (response.adjustment_disposition != "retain")
    ):
        response.decision_id = uuid4()
        evidence = action.trigger_signals if action else suggestion.trigger_signals
        session.add(
            AdaptationDecision(
                id=response.decision_id,
                student_id=context.student_id,
                session_id=context.session_id,
                lesson_id=context.lesson_id,
                segment_id=context.signals.current_segment_id,
                action=action.action if action else "modality_suggestion",
                confidence=action.confidence if action else suggestion.adaptation_confidence,
                trigger_signals=[
                    {"category": item.category, "name": item.name, "confidence": item.confidence}
                    for item in evidence
                ],
            )
        )
    if sitting:
        if (
            response.adjustment_disposition == "apply"
            and response.proactive_adjustment is not None
            and response.proactive_adjustment.action
            in {
                ProactiveAction.OFFER_HINT,
                ProactiveAction.SHOW_SOCRATIC_PANEL,
                ProactiveAction.OFFER_MODALITY_SHIFT,
                ProactiveAction.RECHUNK,
                ProactiveAction.SIMPLIFY,
                ProactiveAction.SLOWER,
                ProactiveAction.CALCULATION_SCAFFOLD,
            }
            and latest is not None
            and current_row is not None
        ):
            delivery["activeSupport"] = {
                "segmentId": str(current_row.id),
                "questionId": latest.question_id,
                "attemptId": str(latest.id),
                "decisionId": str(response.decision_id) if response.decision_id else None,
                "adjustment": response.proactive_adjustment.model_dump(mode="json", by_alias=True),
            }
            if response.proactive_adjustment.action is ProactiveAction.OFFER_HINT:
                delivery["hintedQuestions"] = list(
                    dict.fromkeys(
                        [
                            *delivery.get("hintedQuestions", []),
                            latest.question_id,
                        ]
                    )
                )
        sitting.delivery_state = {**delivery, "recommendations": recommendations}
    await session.commit()
    return response


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
    # A read stays a read. The dated log is written after a lesson, where an
    # accommodation is actually applied, rather than when somebody opens a
    # screen - otherwise the log is a log of page loads.
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


async def _mark_scaffold_answer(request: Request, payload: ScaffoldAttemptRequest) -> bool:
    """Mark the child's answer against the stored calculation, if we hold one.

    Falls back to the client's verdict only when there is nothing on this side
    to mark against, which is the same rule the lesson attempts endpoint
    follows.

    The session is opened here rather than injected into the route, so that an
    attempt needing no marking - and a caller with no business making one -
    does not depend on the database being reachable. Injected, this route
    answered 503 to a request it should have refused with 403.
    """

    if payload.answer is None or payload.lesson_id is None or payload.segment_id is None:
        return bool(payload.response_correct)
    sessions = getattr(request.app.state, "db_sessions", None)
    if sessions is None:
        return bool(payload.response_correct)
    async with sessions() as session:
        segment = await session.scalar(
            select(LessonSegment).where(
                LessonSegment.id == payload.segment_id,
                LessonSegment.lesson_id == payload.lesson_id,
            )
        )
    variant = (segment.calculation_variant or {}) if segment is not None else {}
    expected = str(variant.get("answer") or "").strip()
    if not expected:
        return bool(payload.response_correct)
    return payload.answer.strip().casefold() == expected.casefold()


@router.post(
    "/scaffolds/attempt",
    response_model=ScaffoldDecisionResponse,
    responses={
        403: {"description": "Student: consent_pending, consent_required or consent_withdrawn"},
        503: {"description": "consent_service_unavailable"},
    },
)
async def record_scaffold_attempt(
    payload: ScaffoldAttemptRequest,
    request: Request,
    principal: PrincipalDependency,
    service: ScaffoldFadingDependency,
    consent: StudentLearningConsent = None,
) -> ScaffoldDecisionResponse:
    """Return an already-recorded state for student answerAttemptId receipts.

    Lesson answers apply support transactionally. A student compatibility call
    never applies another fade and never trusts a device verdict. Staff retain
    the separately authorised legacy practice-recording path.
    """

    _ensure_student_or_staff(principal=principal, student_id=payload.student_id)
    if principal.role == "student":
        if payload.answer_attempt_id is None:
            raise HTTPException(
                422,
                detail={
                    "code": "server_marked_attempt_required",
                    "message": "Save the answer first and send its attempt id.",
                },
            )
        sessions = getattr(request.app.state, "db_sessions", None)
        if sessions is None:
            raise HTTPException(503, detail="Learning evidence is temporarily unavailable")
        import hashlib

        from nevo.db.models.mastery import ScaffoldProblemLog
        from nevo.db.models.product import LessonQuestionAttempt

        async with sessions() as session:
            attempt = await session.get(LessonQuestionAttempt, payload.answer_attempt_id)
            if (
                attempt is None
                or attempt.student_id != principal.user_id
                or str(attempt.question_snapshot.get("conceptId")) != str(payload.concept_id)
            ):
                raise HTTPException(404, detail="Answer attempt not found")
            key = hashlib.sha256(f"{attempt.session_id}:{attempt.question_id}".encode()).hexdigest()
            log = await session.scalar(
                select(ScaffoldProblemLog).where(
                    ScaffoldProblemLog.student_id == principal.user_id,
                    ScaffoldProblemLog.problem_id == key,
                )
            )
            if log is None:
                raise HTTPException(
                    409,
                    detail={
                        "code": "scaffold_evidence_pending",
                        "message": "Finish the problem before recording its support state.",
                    },
                )
        state = await service.current_state(
            student_id=principal.user_id, concept_id=payload.concept_id
        )
        return ScaffoldDecisionResponse.from_decision(
            ScaffoldDecision(
                state=state,
                previous_intensity=state.current_intensity,
                next_intensity=state.current_intensity,
                outcome=log.outcome,
                level_changed=False,
                change_reason=None,
                student_message="",
            )
        )
    sessions = getattr(request.app.state, "db_sessions", None)
    if sessions is None:
        raise HTTPException(503, detail="Learning evidence is temporarily unavailable")
    from nevo.api.product_common import require_student_access

    async with sessions() as session:
        await require_student_access(session, principal, payload.student_id)
    correct = await _mark_scaffold_answer(request, payload)
    decision = await service.record_attempt(
        ScaffoldProblemAttempt(
            student_id=payload.student_id,
            concept_id=payload.concept_id,
            problem_id=payload.problem_id,
            response_correct=correct,
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
        available_depths=(
            None if segment.available_depths is None else tuple(segment.available_depths)
        ),
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
    # Only the content location is client context. Scores, timing references,
    # streaks and guardrail counters are reconstructed from persisted evidence.
    return RuntimeSignals(
        current_segment_id=signals.current_segment_id,
        frustration_detected=signals.frustration_detected,
    )


@router.post(
    "/guided-questions/answer",
    response_model=GuidedAnswerResponse,
    responses={
        403: {"description": "Student: consent_pending, consent_required or consent_withdrawn"},
        503: {"description": "consent_service_unavailable"},
    },
)
async def answer_guided_question(
    payload: GuidedAnswerRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
    consent: StudentLearningConsent = None,
) -> GuidedAnswerResponse:
    """Record what a child said back to a guided question.

    The socratic panel could be rendered and not replied to: guidedQuestions
    was a list of strings with no id and no way to send an answer, so the
    dialogue stopped at the first question every time. Ask B19.

    Nothing the child wrote is accepted - only the option they picked or how
    much they wrote, which is what the engine can actually use. The evidence
    is carried on the signal stream, under guided_question_answered, so it
    sits with every other reading about this child rather than in a store of
    its own.
    """

    if principal.role == "student" and principal.user_id != payload.student_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Students can answer only their own guided questions",
        )
    from nevo.api.product_common import require_student_access
    from nevo.intelligence.guided_panel import answer_step

    await require_student_access(session, principal, payload.student_id)
    if principal.role != "student":
        raise HTTPException(403, detail={"code": "student_account_required"})
    if payload.session_id is None:
        raise HTTPException(422, detail={"code": "lesson_session_required"})
    student = await session.get(User, payload.student_id)
    await session.refresh(student, with_for_update={"key_share": True})
    sitting = await session.get(LessonSession, payload.session_id, with_for_update=True)
    if not sitting or sitting.student_id != payload.student_id or sitting.ended_at is not None:
        raise HTTPException(404, detail={"code": "lesson_session_not_found"})
    result = await answer_step(session, sitting, payload)
    await session.commit()
    return GuidedAnswerResponse.model_validate(result)
