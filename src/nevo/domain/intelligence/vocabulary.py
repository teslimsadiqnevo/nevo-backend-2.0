from enum import StrEnum


class AdaptationMode(StrEnum):
    LESSON_LOAD = "lesson_load"
    IN_LESSON = "in_lesson"


class ContentModality(StrEnum):
    VISUAL = "visual"
    AUDIO = "audio"
    TEXT = "text"
    INTERACTIVE = "interactive"


class ContentSegmentType(StrEnum):
    DIAGRAM = "diagram"
    WORKED_EXAMPLE = "worked_example"
    EXPLANATION = "explanation"
    DEFINITION = "definition"
    SUMMARY = "summary"
    PRACTICE = "practice"
    INTERACTION = "interaction"
    CHECKPOINT = "checkpoint"


class LessonContentType(StrEnum):
    EXPLANATORY_TEXT = "explanatory_text"
    VISUAL_DIAGRAM = "visual_diagram"
    WORKED_EXAMPLE = "worked_example"
    PRACTICE_QUESTION = "practice_question"
    DEFINITION = "definition"
    SUMMARY = "summary"
    CALCULATION = "calculation"


class LessonSourceType(StrEnum):
    PDF = "pdf"
    WORD = "word"
    POWERPOINT = "powerpoint"
    GOOGLE_DRIVE = "google_drive"
    ONEDRIVE = "onedrive"
    TEXT = "text"


class ContentParseStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    COMPLETED_WITH_REVIEW = "completed_with_review"
    FAILED = "failed"


class DensityLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ScaffoldingLevel(StrEnum):
    LIGHT = "light"
    STANDARD = "standard"
    STRONG = "strong"


class BreakType(StrEnum):
    MICRO = "micro"
    MOVEMENT = "movement"
    CONSOLIDATION = "consolidation"
    FULL = "full"


class AccommodationType(StrEnum):
    READING = "reading"
    ATTENTION = "attention"
    NUMERICAL = "numerical"


class ScaffoldIntensity(StrEnum):
    FULL_SUPPORT = "full_support"
    PARTIAL_SUPPORT = "partial_support"
    HINTS_ONLY = "hints_only"
    INDEPENDENT = "independent"


class ScaffoldOutcome(StrEnum):
    CORRECT = "correct"
    STRUGGLED = "struggled"


class SegmentReviewReason(StrEnum):
    """Why a parsed segment was flagged for a human look.

    Enumerated so the console can render its own copy per reason instead of
    printing the raw token with underscores swapped for spaces.
    """

    DETERMINISTIC_PARSE_USED = "deterministic_parse_used"
    FEWER_THAN_TWO_MODALITIES = "fewer_than_two_modalities"
    AUDIO_GENERATION_FAILED = "audio_generation_failed"
    CALCULATION_AUDIO_GENERATION_FAILED = "calculation_audio_generation_failed"
    VISUAL_GENERATION_FAILED = "visual_generation_failed"
    VISUAL_VARIANT_IMAGE_GENERATION_FAILED = "visual_variant_image_generation_failed"


class UploadStatus(StrEnum):
    """Lifecycle of an upload job."""

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class UploadStage(StrEnum):
    """Which step of the review flow an upload has reached."""

    LESSONS = "lessons"
    STRUCTURE = "structure"
    COMPLETE = "complete"
