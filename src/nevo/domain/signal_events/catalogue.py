"""What every signal type means, in a form a client can read. Ask B37.

The triggers and payloads were written as comments beside the enum members,
which is a fine place for the person editing the file and no use at all to
somebody generating a client: ``openapi.json`` carried the names and nothing
else, so "it is documented in the enum" was an answer that could not be acted
on.

So the catalogue lives here as data. It does three jobs from one definition:
it renders into the enum's own schema description, it is served from
``GET /api/v1/signals/catalogue`` so a client can assert against it in CI, and
a test refuses to pass while any type is missing from it.

``payload`` names the keys ``eventData`` carries. A key in brackets is
optional. Nothing here is a child's words, a question's text or a tap
coordinate: the stream carries what happened, never what was said.
"""

from __future__ import annotations

from dataclasses import dataclass

from nevo.domain.signal_events.vocabulary import SignalEventType


@dataclass(frozen=True, slots=True)
class SignalContract:
    """One type: when a client sends it, and what it sends with it."""

    trigger: str
    payload: tuple[str, ...]


#: Every type, in the order the enum declares them.
SIGNAL_CONTRACTS: dict[SignalEventType, SignalContract] = {
    SignalEventType.TIME_ON_SEGMENT: SignalContract(
        "The child leaves a segment, or the lesson ends on it. depthShown "
        "says which text version was actually on screen - standard, "
        "simplified or expanded - on every segment, not only the ones an "
        "adaptation touched. Design D23, ask B45.",
        ("segmentId", "durationMs", "depthShown", "[depthRatio]"),
    ),
    SignalEventType.REPLAY: SignalContract(
        "The child plays a finished piece of media again from the start. "
        "Use this for a narration restart too, rather than "
        "narration_replayed, so one restart is not counted twice.",
        ("segmentId", "[channel]"),
    ),
    SignalEventType.SCROLL: SignalContract(
        "The child scrolls within a segment.",
        ("segmentId", "[depthRatio]"),
    ),
    SignalEventType.SIMPLIFY_TRIGGER: SignalContract(
        "The child asks for the simpler wording.", ("segmentId",)
    ),
    SignalEventType.EXPAND_TRIGGER: SignalContract(
        "The child asks for the fuller wording.", ("segmentId",)
    ),
    SignalEventType.SLOWER_TRIGGER: SignalContract(
        "The child asks for a slower pace.", ("segmentId",)
    ),
    SignalEventType.COMPREHENSION_RESPONSE: SignalContract(
        "The child answers a comprehension checkpoint. Correctness is not "
        "sent: it is decided on the server against the stored answer. segmentId "
        "is omitted for an after-lesson assessment item that is not owned by one segment.",
        ("[segmentId]", "questionId", "source: checkpoint|assessment"),
    ),
    SignalEventType.EXIT_ATTEMPT: SignalContract(
        "The child tries to leave mid-lesson.", ("segmentId",)
    ),
    SignalEventType.BREAK_SUGGESTED: SignalContract(
        "Nevo offered a break.", ("breakType: micro|movement|consolidation|full", "trigger")
    ),
    SignalEventType.BREAK_TAKEN: SignalContract(
        "The child accepted an offered break.",
        ("breakType: micro|movement|consolidation|full", "trigger"),
    ),
    SignalEventType.BREAK_DECLINED: SignalContract(
        "The child refused an offered break. Without this the engine cannot "
        'tell "not now" from no answer and may offer again a minute later.',
        ("breakType: micro|movement|consolidation|full", "trigger"),
    ),
    SignalEventType.BREAK_START: SignalContract(
        "A break actually began.",
        ("breakType: micro|movement|consolidation|full", "trigger"),
    ),
    SignalEventType.BREAK_END: SignalContract(
        "A break ended. With break_start this is how long it lasted, which is "
        "the part that says whether it helped.",
        ("breakType: micro|movement|consolidation|full", "trigger", "durationMs"),
    ),
    SignalEventType.FEELING_CHECKIN: SignalContract(
        "The child answers the consolidation break's question about how they are getting on.",
        ("response",),
    ),
    SignalEventType.MODULE_BOUNDARY_REACHED: SignalContract(
        "The child reaches the end of a module.", ("moduleId",)
    ),
    SignalEventType.MODULE_BOUNDARY_ACTION: SignalContract(
        "What they chose there.", ("moduleId", "action")
    ),
    SignalEventType.ENGAGEMENT_SIGNAL: SignalContract(
        "A reading the named types do not already cover. value is a non-negative "
        "number: focus_drop and steady_progress use milliseconds; task_switch, "
        "navigation_fragmentation and rapid_guessing use a count; "
        "return_after_pause uses the pause duration in milliseconds. The type "
        "is a last resort: use a named event where one exists.",
        (
            (
                "indicator: focus_drop|task_switch|navigation_fragmentation|"
                "rapid_guessing|steady_progress|return_after_pause"
            ),
            "value",
        ),
    ),
    SignalEventType.MODALITY_SUGGESTION_SHOWN: SignalContract(
        "Nevo offered a different modality.", ("segmentId", "suggested")
    ),
    SignalEventType.MODALITY_SUGGESTION_ACCEPTED: SignalContract(
        "The child took the offer.", ("segmentId", "suggested")
    ),
    SignalEventType.MODALITY_SUGGESTION_DECLINED: SignalContract(
        "The child refused it.", ("segmentId", "suggested")
    ),
    SignalEventType.MODALITY_SUGGESTION_IGNORED: SignalContract(
        "The offer was shown and neither taken nor refused before the child moved on.",
        ("segmentId", "suggested"),
    ),
    SignalEventType.MODALITY_SWITCH_OUTCOME: SignalContract(
        "Sent once when the next segment entered in the new modality is left "
        "or completed. That entry-to-exit interval is a full segment; it has "
        "no minimum number of seconds. timeOnSegment is milliseconds. The "
        "comprehension and engagement scores are supplied aggregates: either "
        "0-1 ratios or 0-100 scores, normalised on the server; raw interaction "
        "data is never sent. One per switch. Ask B38.",
        (
            "segmentId",
            "[from]",
            "[to]",
            "[outcome: better|worse|no_change]",
            "[modality]",
            "[comprehensionScore]",
            "[engagementScore]",
            "[timeOnSegment]",
        ),
    ),
    SignalEventType.MODALITY_MANUAL_SWITCH: SignalContract(
        "The child changed modality themselves, with nothing offered.",
        ("segmentId", "from", "to"),
    ),
    SignalEventType.CALCULATION_STEP_RESPONSE: SignalContract(
        "The child answers one step of a calculation.",
        ("segmentId", "stepId"),
    ),
    SignalEventType.CALCULATION_COMPLETE: SignalContract(
        "The child finishes a calculation.", ("segmentId",)
    ),
    SignalEventType.NARRATION_PLAYED: SignalContract(
        "Narration starts for the first time on a segment.", ("segmentId",)
    ),
    SignalEventType.NARRATION_REPLAYED: SignalContract(
        "Reserved. Send replay for a restart instead, so one restart is not "
        "counted under two types. Ask B39.",
        ("segmentId",),
    ),
    SignalEventType.MANIPULATIVE_PIECE_PLACED: SignalContract(
        "The child places a draggable piece.", ("segmentId", "[stepId]")
    ),
    SignalEventType.ASK_NEVO_QUESTION_STUDENT: SignalContract(
        "A child asks Nevo a question, on an ask_nevo session.",
        ("interactionId", "studentId", "currentPage", "questionCategory"),
    ),
    SignalEventType.ASK_NEVO_QUESTION_TEACHER: SignalContract(
        "A teacher asks Nevo a question.",
        ("interactionId", "role", "currentPage", "questionCategory"),
    ),
    SignalEventType.ASK_NEVO_CANNOT_HELP: SignalContract(
        "Ask Nevo declined to answer and handed the asker on.",
        ("interactionId", "role", "currentPage"),
    ),
    SignalEventType.ASK_NEVO_REDIRECT_USED: SignalContract(
        "The asker followed where it sent them.",
        ("interactionId", "role", "currentPage", "redirectTarget"),
    ),
    SignalEventType.ADAPTATION_SUPPRESSED: SignalContract(
        "Server-written. An adaptation was decided and then held back by a "
        "rate limit or a cooldown. Clients do not send this.",
        ("attemptedType", "reason"),
    ),
    SignalEventType.MEDIA_LOAD_FAILED: SignalContract(
        "A picture or a recording did not load. reason is one of offline, "
        "refresh_failed, load_error.",
        ("segmentId", "channel", "reason"),
    ),
    SignalEventType.SYSTEM_BUSY: SignalContract(
        "The system owned the wait, not the child - audio playing, a dialog "
        "open, a transition running. Counted as idle time until this existed.",
        ("reason", "durationMs"),
    ),
    SignalEventType.TAP_BLOCKED: SignalContract(
        "A tap the interface refused because something was loading or "
        "disabled. Repeated refused taps are a child trying, which reads as a "
        "child doing nothing unless it is reported.",
        ("target", "reason"),
    ),
    SignalEventType.SESSION_CONTEXT: SignalContract(
        "Once per session, first. Dwell times on a phone are not dwell times "
        "on a desktop, and a child with reduced motion on is not a child "
        "ignoring an animation.",
        ("formFactor", "reducedMotion"),
    ),
    SignalEventType.READING_CHUNK_VIEWED: SignalContract(
        "A stable reading chunk entered view or was passed. A later entered "
        "event after passed is a reread; formFactor keeps scrolling patterns comparable.",
        ("segmentId", "chunkId", "action: entered|passed", "formFactor"),
    ),
    SignalEventType.BASELINE_MODULE_START: SignalContract(
        "A baseline module begins.", ("moduleId",)
    ),
    SignalEventType.BASELINE_MODULE_COMPLETE: SignalContract(
        "A baseline module finishes.", ("moduleId",)
    ),
    SignalEventType.BASELINE_SUBMITTED: SignalContract(
        "The baseline is submitted. With the two above, an abandoned baseline "
        "can be told from one never started.",
        (),
    ),
    SignalEventType.HINT_OFFERED: SignalContract(
        "Nevo offered a hint, whether or not the child asked for one.",
        ("segmentId", "[conceptId]", "[hintIndex]"),
    ),
    SignalEventType.HINT_USED: SignalContract(
        "The child acted on a hint: opened one they had to open, or moved on "
        "after one shown in full. A hint shown and ignored is hint_offered "
        "alone. Ask B41.",
        ("segmentId", "[conceptId]", "[hintIndex]"),
    ),
    SignalEventType.STEP_UP_OFFERED: SignalContract("Nevo offered harder work.", ("segmentId",)),
    SignalEventType.STEP_UP_ACCEPTED: SignalContract("The child took it.", ("segmentId",)),
    SignalEventType.STEP_UP_DECLINED: SignalContract("The child refused it.", ("segmentId",)),
    SignalEventType.GUIDED_QUESTION_SHOWN: SignalContract(
        "A guided question was put to the child.",
        ("segmentId", "promptId"),
    ),
    SignalEventType.GUIDED_QUESTION_ANSWERED: SignalContract(
        "Server-written by POST /api/intelligence/guided-questions/answer. "
        "Clients do not send this, or one reply would count twice. Ask B41.",
        ("segmentId", "promptId", "outcome"),
    ),
}


def render_catalogue() -> str:
    """The catalogue as the enum's own schema description."""

    lines = [
        "What each signal means and what it carries.",
        "",
        "Keys in brackets are optional. Types marked server-written are "
        "produced here and must not be sent by a client, or they count twice.",
        "",
    ]
    for event_type, contract in SIGNAL_CONTRACTS.items():
        payload = ", ".join(contract.payload) if contract.payload else "no payload"
        lines.append(f"- `{event_type.value}` — {contract.trigger} Carries: {payload}.")
    return "\n".join(lines)


#: Attached to the enum itself, because that is where a generated client
#: looks. Pydantic renders a StrEnum's docstring as the schema description,
#: so this one definition reaches openapi.json without a second copy.
SignalEventType.__doc__ = render_catalogue()
