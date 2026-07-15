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
