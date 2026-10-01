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
    #: The child accepted a break that was offered. ``{"trigger": ...}``,
    #: naming which offer they accepted. Sent at the moment of acceptance;
    #: BREAK_START and BREAK_END below carry how long it actually lasted.
    BREAK_TAKEN = "break_taken"
    #: A break actually started and ended. break_suggested and break_taken say
    #: Nevo offered one and the child accepted; these two say how long it
    #: lasted, which is the part that tells you whether it helped.
    BREAK_START = "break_start"
    BREAK_END = "break_end"
    #: What the child said when the consolidation break asked how they were
    #: getting on. It was being asked and the answer discarded, because there
    #: was no event type to carry it.
    FEELING_CHECKIN = "feeling_checkin"
    #: The learner reached the end of a module. A natural place to pause, and
    #: the boundary the break logic wants to reason about.
    MODULE_BOUNDARY_REACHED = "module_boundary_reached"
    #: What they did there. ``{"moduleId": ..., "action": "continue"|"break"}``
    #: - the two buttons the boundary offers.
    #:
    #: The sibling of the one above, and the only place in the product where a
    #: child is offered a break and answers. Without it the offer is recorded
    #: and the answer is not, which is the half that says whether offering
    #: helped. The client has been collecting these and dropping them at the
    #: door: it filters every event against a copy of this enum before posting,
    #: because one unknown type refuses the whole batch.
    MODULE_BOUNDARY_ACTION = "module_boundary_action"
    #: A general-purpose engagement reading, emitted on no fixed trigger.
    #:
    #: Deliberately open where the ones around it are not. ``eventData`` takes
    #: ``{"indicator": ..., "value": ...}``: whatever the client can observe
    #: that the specific types above do not already cover. It is the type of
    #: last resort - if a reading has a named type, that type is used, because
    #: the engine can reason about a named one and can only count these.
    ENGAGEMENT_SIGNAL = "engagement_signal"
    MODALITY_SUGGESTION_SHOWN = "modality_suggestion_shown"
    MODALITY_SUGGESTION_ACCEPTED = "modality_suggestion_accepted"
    MODALITY_SUGGESTION_DECLINED = "modality_suggestion_declined"
    MODALITY_SUGGESTION_IGNORED = "modality_suggestion_ignored"
    #: Whether changing modality helped, sent once the child has spent enough
    #: time in the new one to tell. ``{"from": ..., "to": ..., "outcome":
    #: "better"|"worse"|"no_change"}``. The sibling of the four
    #: MODALITY_SUGGESTION_* types: those say what was offered and what the
    #: child did, this says whether it was worth offering.
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
    #: A picture or a recording did not load. ``{"segmentId": ..., "channel":
    #: "image"|"audio", "reason": ...}``.
    #:
    #: Without this the engine reads a child sitting in front of a broken
    #: image as a child disengaging from the lesson, and may shift modality
    #: away from the one channel that was working. SCRUM-204 asks that no rung
    #: exist with nothing behind it; this is the same rule for signals.
    MEDIA_LOAD_FAILED = "media_load_failed"
    #: The system owned the wait, not the child. ``{"reason": ...,
    #: "durationMs": ...}`` - audio playing, a dialog open, a transition
    #: running.
    #:
    #: Counted as idle time until now, which is the engine concluding a child
    #: had stopped paying attention while it was the one holding them up.
    SYSTEM_BUSY = "system_busy"
    #: A tap that the interface refused, because something was still loading
    #: or a control was disabled. ``{"target": ..., "reason": ...}``. Repeated
    #: refused taps are a child trying, which reads identically to a child
    #: doing nothing unless it is reported.
    TAP_BLOCKED = "tap_blocked"
    #: What the child is using, sent once per session.
    #: ``{"formFactor": "phone"|"tablet"|"desktop", "reducedMotion": bool}``.
    #: Dwell times on a phone are not dwell times on a desktop, and a child
    #: with reduced motion on is not a child ignoring an animation.
    SESSION_CONTEXT = "session_context"
    #: The baseline's own lifecycle. Reported so an abandoned baseline can be
    #: told apart from one that was never started, which is the difference
    #: between a child who found it too hard and a child who never saw it.
    BASELINE_MODULE_START = "baseline_module_start"
    BASELINE_MODULE_COMPLETE = "baseline_module_complete"
    BASELINE_SUBMITTED = "baseline_submitted"
    #: Support the child actually used, as opposed to support offered.
    #:
    #: The calculation solver's hint has been live and reporting nothing, so
    #: the one piece of evidence about whether hints help has been thrown away
    #: every time it was produced. ``{"segmentId": ..., "conceptId": ...}``,
    #: plus ``{"hintIndex": ...}`` where there is a ladder of them.
    HINT_OFFERED = "hint_offered"
    HINT_USED = "hint_used"
    #: A step-up offer - the same ladder in the other direction.
    STEP_UP_OFFERED = "step_up_offered"
    STEP_UP_ACCEPTED = "step_up_accepted"
    STEP_UP_DECLINED = "step_up_declined"
    #: A guided question was put to the child, and what they said back.
    #: ``{"segmentId": ..., "conceptId": ..., "questionIndex": ...}``, and on
    #: the answer ``{"optionId": ...}`` or ``{"responseLength": ...}`` - never
    #: the child's own words, which stay on the device.
    GUIDED_QUESTION_SHOWN = "guided_question_shown"
    GUIDED_QUESTION_ANSWERED = "guided_question_answered"


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
