from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

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
from nevo.domain.learner_profiles.vocabulary import (
    ChannelPreferenceStrength,
    ConfidenceLevel,
)


@dataclass(frozen=True, slots=True)
class ChannelPreference:
    value: ChannelPreferenceStrength | None
    confidence: ConfidenceLevel


@dataclass(frozen=True, slots=True)
class LearnerProfileSnapshot:
    visual_spatial_preference: ChannelPreference
    auditory_preference: ChannelPreference
    reading_writing_preference: ChannelPreference
    interactive_kinesthetic_preference: ChannelPreference
    working_memory_capacity: int | None = None
    attention_span: int | None = None


@dataclass(frozen=True, slots=True)
class ContentSegment:
    id: str
    segment_type: ContentSegmentType
    available_modalities: tuple[ContentModality, ...]
    concept_id: str | None = None
    estimated_minutes: float | None = None
    passive: bool = False
    title: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeSignals:
    current_segment_id: str | None = None
    current_modality: ContentModality | None = None
    available_modalities: tuple[ContentModality, ...] = ()
    continuous_minutes: float = 0
    engagement_score: float | None = None
    engagement_baseline: float | None = None
    engagement_below_baseline_seconds: int = 0
    comprehension_score: float | None = None
    session_average_comprehension: float | None = None
    consecutive_errors: int = 0
    replay_count_on_segment: int = 0
    same_segment_suggestion_shown: bool = False
    segments_since_last_suggestion: int | None = None
    declined_modalities: tuple[ContentModality, ...] = ()
    session_decline_count: int = 0
    accuracy_below_baseline: bool = False
    response_time_below_baseline: bool = False
    midpoint_reached: bool = False
    current_segment_elapsed_seconds: int | None = None
    seconds_since_last_adaptation: int | None = None
    session_modality_shift_count: int | None = None


@dataclass(frozen=True, slots=True)
class BreakThresholdResult:
    triggered_thresholds: tuple[str, ...]
    severity: str
    break_type: BreakType | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class SegmentAdaptation:
    segment_id: str
    modality: ContentModality
    density: DensityLevel
    scaffolding: ScaffoldingLevel
    priority: int


@dataclass(frozen=True, slots=True)
class ProactiveAdjustment:
    action: str
    reason: str


@dataclass(frozen=True, slots=True)
class ModalitySuggestion:
    suggested: ContentModality
    trigger_reason: str
    confidence: ConfidenceLevel


@dataclass(frozen=True, slots=True)
class SuppressedAdaptationAttempt:
    attempted_type: str
    reason: str
    current_segment_id: str | None
    current_modality: ContentModality | None
    suggested_modality: ContentModality | None


@dataclass(frozen=True, slots=True)
class AdaptationRequest:
    student_id: UUID
    lesson_id: UUID
    mode: AdaptationMode
    segments: tuple[ContentSegment, ...]
    signals: RuntimeSignals = field(default_factory=RuntimeSignals)
    session_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class AdaptationPlan:
    lesson_id: UUID
    segments: tuple[SegmentAdaptation, ...]
    break_suggestion: BreakThresholdResult
    proactive_adjustment: ProactiveAdjustment | None
    modality_suggestion: ModalitySuggestion | None
    source: str
    suppressed_attempt: SuppressedAdaptationAttempt | None = None


@dataclass(frozen=True, slots=True)
class AccommodationSignal:
    accommodation: AccommodationType
    frontend_signal: str
    evidence: tuple[str, ...]
    lesson_count: int


@dataclass(frozen=True, slots=True)
class AccommodationAnalysis:
    student_id: UUID
    active: tuple[AccommodationSignal, ...]
    source: str


@dataclass(frozen=True, slots=True)
class BehaviourPatternAggregate:
    lesson_count: int
    reading_latency_lessons: int = 0
    backward_scroll_lessons: int = 0
    word_pause_lessons: int = 0
    low_text_completion_lessons: int = 0
    task_switch_lessons: int = 0
    erratic_navigation_lessons: int = 0
    focus_drop_lessons: int = 0
    fragmented_flow_lessons: int = 0
    maths_lesson_count: int = 0
    calculation_latency_lessons: int = 0
    numerical_correction_lessons: int = 0
    repeated_numeric_mistake_lessons: int = 0
    numeric_hesitation_lessons: int = 0


@dataclass(frozen=True, slots=True)
class ScaffoldConceptState:
    student_id: UUID
    concept_id: UUID
    current_intensity: ScaffoldIntensity
    consecutive_correct: int = 0
    response_time_improvement_streak: int = 0
    reduced_hint_streak: int = 0
    last_response_time_ms: int | None = None
    last_hint_count: int | None = None


@dataclass(frozen=True, slots=True)
class ScaffoldProblemAttempt:
    student_id: UUID
    concept_id: UUID
    problem_id: str
    response_correct: bool
    scaffold_intensity: ScaffoldIntensity | None = None
    response_time_ms: int | None = None
    expected_response_time_ms: int | None = None
    hint_count: int = 0


@dataclass(frozen=True, slots=True)
class ScaffoldDecision:
    state: ScaffoldConceptState
    previous_intensity: ScaffoldIntensity
    next_intensity: ScaffoldIntensity
    outcome: ScaffoldOutcome
    level_changed: bool
    change_reason: str | None
    student_message: str


@dataclass(frozen=True, slots=True)
class ScaffoldProblemLogEntry:
    student_id: UUID
    concept_id: UUID
    problem_id: str
    scaffold_intensity: ScaffoldIntensity
    outcome: ScaffoldOutcome
    response_time_ms: int | None
    expected_response_time_ms: int | None
    hint_count: int
    next_scaffold_intensity: ScaffoldIntensity
    level_changed: bool
    change_reason: str | None


@dataclass(frozen=True, slots=True)
class AdaptationEventLogRecord:
    id: UUID
    student_id: UUID
    student_first_name: str
    lesson_id: UUID
    lesson_title: str
    timestamp: datetime
    trigger: str
    adaptation: str
    event_type: str
