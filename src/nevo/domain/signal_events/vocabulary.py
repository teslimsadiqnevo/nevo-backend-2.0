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


class LessonCompletionStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    EXITED = "exited"
