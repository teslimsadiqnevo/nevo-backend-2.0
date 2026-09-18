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
    CALCULATION_VARIANT_TOO_FEW_STEPS = "calculation_variant_too_few_steps"
    CALCULATION_STEP_MISSING_PROMPT = "calculation_step_missing_prompt"
    CALCULATION_STEP_UNKNOWN_INPUT_TYPE = "calculation_step_unknown_input_type"
    CALCULATION_STEP_MISSING_ANSWER = "calculation_step_missing_answer"
    CALCULATION_STEP_MISSING_OPTIONS = "calculation_step_missing_options"
    CALCULATION_VARIANT_MISSING_MANIPULATIVE = "calculation_variant_missing_manipulative"
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


class ClassInsightState(StrEnum):
    """Which of three things the weekly class view is saying.

    The console was deciding this itself from the length of three arrays,
    which put a threshold in the client and could not tell a settled week from
    a new class - so a class having a good week was told insights were still
    being gathered. The engine owns the threshold and the copy; the client
    renders what it is given.
    """

    #: There is a pattern worth pointing at.
    SUMMARY = "summary"
    #: The engine looked at a full week and found nothing needing attention.
    #: A finding, not an absence of one.
    SETTLED = "settled"
    #: Not enough has happened yet to say either way.
    GATHERING = "gathering"


class ProactiveAction(StrEnum):
    """What the engine can ask a lesson to do next.

    Typed because a bare string put the vocabulary in a document instead of
    the contract, and a client had no way to know which values it must handle.

    The first three are the only ones the engine produces today. The last two
    are declared because the shapes that carry them exist and a client renders
    them; nothing emits them yet, and a value that is never sent is honest in
    a way an undocumented string was not.
    """

    SIMPLIFY = "simplify"
    SLOWER = "slower"
    EXPAND = "expand"
    #: Carries hint text. A hint with nothing to say is not a hint.
    OFFER_HINT = "offer_hint"
    #: Carries the questions the panel walks through.
    SHOW_SOCRATIC_PANEL = "show_socratic_panel"


class ManipulativeKind(StrEnum):
    """What a learner drags, when a calculation step asks them to.

    A drag step had no structure to render, so drag was refused on generated
    content and the one place modalities layer rather than switch could not
    happen.
    """

    FRACTION_BAR = "fraction_bar"
    NUMBER_LINE = "number_line"
    ARRAY = "array"
    PLACE_VALUE = "place_value"
    COUNTERS = "counters"
