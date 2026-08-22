from nevo.domain.signal_events.vocabulary import SignalEventType
from nevo.intelligence.adaptation_log import (
    adaptation_plain_language,
    trigger_plain_language,
)


def test_modality_suggestion_renders_plain_language_for_admin_log() -> None:
    event_data = {
        "triggerReason": "combined",
        "currentModality": "text",
        "suggestedModality": "visual",
    }

    assert (
        trigger_plain_language(
            SignalEventType.MODALITY_SUGGESTION_SHOWN,
            event_data,
        )
        == "Comprehension declining + engagement drop"
    )
    assert (
        adaptation_plain_language(
            SignalEventType.MODALITY_SUGGESTION_SHOWN,
            event_data,
        )
        == "Text -> Visual"
    )


def test_non_modality_adaptations_render_content_shift() -> None:
    assert (
        adaptation_plain_language(SignalEventType.SIMPLIFY_TRIGGER, {})
        == "Original -> Simplified"
    )
    assert (
        adaptation_plain_language(SignalEventType.SLOWER_TRIGGER, {})
        == "Standard pace -> Slower pace"
    )
    assert (
        trigger_plain_language(SignalEventType.BREAK_SUGGESTED, {})
        == "Attention or effort pattern shift"
    )
