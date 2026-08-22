from dataclasses import dataclass, field
from uuid import UUID

from nevo.domain.intelligence.vocabulary import (
    AccommodationType,
    AdaptationMode,
    BreakType,
    ContentModality,
    ContentSegmentType,
    DensityLevel,
    ScaffoldingLevel,
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
class AdaptationRequest:
    student_id: UUID
    lesson_id: UUID
    mode: AdaptationMode
    segments: tuple[ContentSegment, ...]
    signals: RuntimeSignals = field(default_factory=RuntimeSignals)


@dataclass(frozen=True, slots=True)
class AdaptationPlan:
    lesson_id: UUID
    segments: tuple[SegmentAdaptation, ...]
    break_suggestion: BreakThresholdResult
    proactive_adjustment: ProactiveAdjustment | None
    modality_suggestion: ModalitySuggestion | None
    source: str


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
