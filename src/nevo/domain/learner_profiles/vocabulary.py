from enum import StrEnum

CANONICAL_PROFILE_DIMENSIONS = (
    "visual_spatial_preference",
    "auditory_preference",
    "reading_writing_preference",
    "interactive_kinesthetic_preference",
    "cognitive_load_threshold",
    "processing_speed",
    "working_memory_capacity",
    "attention_span",
    "performance_sensitivity",
)

# Contract tests apply this policy to database identifiers and enum values only.
PROHIBITED_SCHEMA_TERMS = frozenset(
    {
        "adhd",
        "autism",
        "autistic",
        "diagnosis",
        "diagnostic",
        "disability",
        "disorder",
        "dyslexia",
        "dyslexic",
        "medical_condition",
        "neuro_profile",
        "neurodivergent",
        "special_needs",
    }
)


class ConfidenceLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ProcessingChannelPreference(StrEnum):
    VISUAL = "visual"
    AUDITORY = "auditory"
    TEXTUAL = "textual"
    INTERACTIVE = "interactive"
    MULTIMODAL = "multimodal"
    UNDETERMINED = "undetermined"


class ChannelPreferenceStrength(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    STRONG = "strong"


class ProfileChangeSource(StrEnum):
    SYSTEM_INFERENCE = "system_inference"
    EDUCATOR_REVIEW = "educator_review"
    LEARNER_INPUT = "learner_input"
    ROSTER_IMPORT = "roster_import"
    CORRECTION = "correction"


class ProfileAttentionFlagStatus(StrEnum):
    OPEN = "open"
    REVIEWED = "reviewed"
    DISMISSED = "dismissed"


class GamingSuspicionLevel(StrEnum):
    """Stored-only signal that observed effort may not reflect real effort.

    SCRUM-62 keeps this internal. Nothing reads it at runtime yet, and it is
    never surfaced verbatim: see
    ``nevo.domain.learner_profiles.gaming_rules`` for the positively framed
    copy a teacher actually sees.
    """

    NONE = "none"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class EngagementAnomalyType(StrEnum):
    """Shape of a recorded deviation from a learner's own prior baseline."""

    RESPONSE_TIME_SLOWDOWN = "response_time_slowdown"
    ERROR_RATE_SPIKE = "error_rate_spike"
    ABANDONED_ATTEMPT_SPIKE = "abandoned_attempt_spike"


class EngagementAnomalyScope(StrEnum):
    """How widely an anomaly spread across content types.

    Breadth is the discriminator. A learner who genuinely finds one content
    type hard slows down on that content type; a learner steering the system
    slows down everywhere at once.
    """

    SINGLE_CONTENT_TYPE = "single_content_type"
    ALL_CONTENT_TYPES = "all_content_types"
