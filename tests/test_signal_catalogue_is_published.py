"""The signal contracts reach a client, not just a reader of the source. B37.

The triggers and payloads were written as comments beside the enum members.
That is a good place for whoever edits the file and no use at all to somebody
generating a client: openapi.json carried the names and nothing else, so "it
is documented in the enum" was an answer that could not be acted on.
"""

from __future__ import annotations

from nevo.domain.signal_events.catalogue import SIGNAL_CONTRACTS
from nevo.domain.signal_events.vocabulary import SignalEventType
from nevo.main import app

SPEC = app.openapi()


def test_every_type_is_documented() -> None:
    # A type nobody can describe is a type nobody can send correctly.
    assert set(SIGNAL_CONTRACTS) == set(SignalEventType)


def test_the_description_reaches_the_published_spec() -> None:
    schema = SPEC["components"]["schemas"]["SignalEventType"]

    assert "description" in schema, "openapi.json carries names only again"
    for event_type in SignalEventType:
        assert event_type.value in schema["description"], event_type.value


def test_a_client_can_assert_against_the_catalogue() -> None:
    assert "/api/signals/catalogue" in SPEC["paths"]


def test_the_payloads_olayinka_listed_are_what_we_expect() -> None:
    # He asked us to confirm five of them rather than guess. These are the
    # confirmations, pinned so a later edit cannot quietly disagree with the
    # answer he was given.
    expected = {
        SignalEventType.SESSION_CONTEXT: ("formFactor", "reducedMotion"),
        SignalEventType.GUIDED_QUESTION_SHOWN: ("segmentId", "promptId"),
        SignalEventType.MEDIA_LOAD_FAILED: ("segmentId", "channel", "reason"),
    }
    for event_type, payload in expected.items():
        assert SIGNAL_CONTRACTS[event_type].payload == payload, event_type.value
    # hint_offered carries the segment and may carry which hint it was.
    assert SIGNAL_CONTRACTS[SignalEventType.HINT_OFFERED].payload[0] == "segmentId"


def test_the_server_written_ones_are_marked_as_such() -> None:
    # A client sending one of these would have it counted twice.
    for event_type in (
        SignalEventType.GUIDED_QUESTION_ANSWERED,
        SignalEventType.ADAPTATION_SUPPRESSED,
    ):
        assert "Server-written" in SIGNAL_CONTRACTS[event_type].trigger


def test_a_narration_restart_has_one_home() -> None:
    # Sent as replay. narration_replayed is reserved so one restart is not
    # counted under two types. Ask B39.
    assert "replay" in SIGNAL_CONTRACTS[SignalEventType.NARRATION_REPLAYED].trigger
    assert "restart" in SIGNAL_CONTRACTS[SignalEventType.REPLAY].trigger


def test_time_and_after_lesson_units_are_unambiguous() -> None:
    outcome = SIGNAL_CONTRACTS[SignalEventType.MODALITY_SWITCH_OUTCOME]
    comprehension = SIGNAL_CONTRACTS[SignalEventType.COMPREHENSION_RESPONSE]

    assert "milliseconds" in outcome.trigger
    assert comprehension.payload[0] == "[segmentId]"
