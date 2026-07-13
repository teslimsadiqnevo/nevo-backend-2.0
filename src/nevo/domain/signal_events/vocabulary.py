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

