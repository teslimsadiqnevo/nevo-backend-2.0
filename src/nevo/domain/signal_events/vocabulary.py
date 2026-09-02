from enum import StrEnum


class SignalEventType(StrEnum):
    TIME_ON_SEGMENT = "time_on_segment"
    REPLAY = "replay"
    SCROLL = "scroll"
    SIMPLIFY_TRIGGER = "simplify_trigger"
    EXPAND_TRIGGER = "expand_trigger"
    SLOWER_TRIGGER = "slower_trigger"
    COMPREHENSION_RESPONSE = "comprehension_response"
    EXIT_ATTEMPT = "exit_attempt"
    BREAK_SUGGESTED = "break_suggested"
    BREAK_TAKEN = "break_taken"
    ENGAGEMENT_SIGNAL = "engagement_signal"
    MODALITY_SUGGESTION_SHOWN = "modality_suggestion_shown"
    MODALITY_SUGGESTION_ACCEPTED = "modality_suggestion_accepted"
    MODALITY_SUGGESTION_DECLINED = "modality_suggestion_declined"
    MODALITY_SUGGESTION_IGNORED = "modality_suggestion_ignored"
    MODALITY_SWITCH_OUTCOME = "modality_switch_outcome"
    MODALITY_MANUAL_SWITCH = "modality_manual_switch"
    CALCULATION_STEP_RESPONSE = "calculation_step_response"
    CALCULATION_COMPLETE = "calculation_complete"
    NARRATION_PLAYED = "narration_played"
    NARRATION_REPLAYED = "narration_replayed"
    MANIPULATIVE_PIECE_PLACED = "manipulative_piece_placed"
    ASK_NEVO_QUESTION_STUDENT = "ask_nevo_question_student"
    ASK_NEVO_QUESTION_TEACHER = "ask_nevo_question_teacher"
    ASK_NEVO_CANNOT_HELP = "ask_nevo_cannot_help"
    ASK_NEVO_REDIRECT_USED = "ask_nevo_redirect_used"
    ADAPTATION_SUPPRESSED = "adaptation_suppressed"


class LessonCompletionStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    EXITED = "exited"


class LearnerObservationPattern(StrEnum):
    """What a roster observation can say about a learner.

    A closed set, and deliberately so. These are derived from lesson sessions
    and a fixed list of signal events - never free text, model output, or
    anything the learner authored. Typing it puts that guarantee in the schema
    rather than in the reviewer's memory: a client can see there is nothing
    open-ended here without taking anyone's word for it.
    """

    COMPLETED_LESSONS = "completed_lessons"
    REVISITED_CONTENT = "revisited_content"
    STEADIER_PACE = "steadier_pace"
    TRIED_ANOTHER_FORMAT = "tried_another_format"
    NO_RECENT_PATTERN = "no_recent_pattern"
