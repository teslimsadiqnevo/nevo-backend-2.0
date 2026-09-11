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
    CALCULATION = "calculation"


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
    CALCULATION_VARIANT_MALFORMED = "calculation_variant_malformed"
    CALCULATION_VARIANT_MISSING_ANSWER = "calculation_variant_missing_answer"
    CALCULATION_SEGMENT_HAS_NO_INTERACTIVE_DELIVERY = (
        "calculation_segment_has_no_interactive_delivery"
    )
    #: The model asked for a human look in words of its own. Kept as a reason
    #: the console can render, rather than as prose it cannot.
    MODEL_FLAGGED_FOR_REVIEW = "model_flagged_for_review"


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


class AssignmentStatus(StrEnum):
    """Lifecycle of a lesson assignment."""

    ASSIGNED = "assigned"
    CANCELLED = "cancelled"


class AssignmentType(StrEnum):
    """Whether an assignment was made to a class or to one student."""

    CLASS = "class"
    STUDENT = "student"


class LessonScope(StrEnum):
    """Which lessons a listing is asking for.

    A teacher defaults to MINE. A shared library is useful to browse, but a
    dashboard that opens on every lesson anyone in the school ever made is not
    a view of that teacher's work.
    """

    MINE = "mine"
    SCHOOL = "school"
