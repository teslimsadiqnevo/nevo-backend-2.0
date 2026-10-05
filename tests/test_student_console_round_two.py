"""Round two of the student console's asks. B25, B40, B46, B52, B54-B61, B65.

Each of these was something the console drew against and the backend either
did not carry, carried under a name nobody could act on, or sent when it
should not have.
"""

from __future__ import annotations

from nevo.main import app

SPEC = app.openapi()
SCHEMAS = SPEC["components"]["schemas"]


def test_b25_a_segment_says_which_concept_it_teaches() -> None:
    from nevo.db.models.content import LessonSegment

    # Without it the solver can ask about the sum in front of the child but
    # not about the idea they are stuck on.
    assert "concept_id" in {column.name for column in LessonSegment.__table__.columns}
    assert "conceptId" in SCHEMAS["LessonSegmentResponse"]["properties"]
    assert "conceptId" in SCHEMAS["CalculationVariant"]["properties"]


def test_b25_the_calculation_is_already_data_not_a_picture() -> None:
    scaffold = SCHEMAS["CalculationScaffold"]["properties"]

    # Its drawing kind and its values, so nothing has to be generated.
    assert {"kind", "parts", "rows", "marks", "labels"} <= set(scaffold)
    variant = SCHEMAS["CalculationVariant"]["properties"]
    assert {"expression", "steps", "scaffold", "answer"} <= set(variant)


def test_b40_a_declined_break_can_be_reported() -> None:
    from nevo.domain.signal_events.vocabulary import SignalEventType

    # Without it the engine could offer again a minute after "Not now".
    assert SignalEventType.BREAK_DECLINED.value == "break_declined"


def test_b46_the_adjustment_names_its_segment() -> None:
    assert "segmentId" in SCHEMAS["ProactiveAdjustmentResponse"]["properties"]


def test_b52_a_library_lesson_can_be_drawn_on_home() -> None:
    recent = SCHEMAS["RecentProgressResponse"]["properties"]

    assert {"title", "subject", "segmentCount"} <= set(recent)


def test_b54_a_device_task_day_still_counts_as_done() -> None:
    from nevo.api.frontend_unblockers import BaselinePromptAnswer

    # On five days of six the warm-up runs on the device and answers no
    # served question. Nothing was sent, doneToday stayed false, and a second
    # tablet offered the child a second run and took a second measurement.
    assert BaselinePromptAnswer.model_validate({}).item_id is None
    # An item without an answer is still a mistake.
    import pytest

    with pytest.raises(ValueError):
        BaselinePromptAnswer.model_validate({"itemId": "x"})


def test_b55_the_warm_up_reply_carries_no_verdict() -> None:
    # Scored here; the device has no need to hold a judgement about a child.
    assert "correct" not in SCHEMAS["BaselinePromptResult"]["properties"]


def test_b58_a_closed_account_is_not_a_paused_one() -> None:
    from nevo.auth.errors import AccountClosedError, AccountPausedError

    # A removed child told their account is "on pause" is being told their
    # school can turn it back on, which is not true.
    assert AccountClosedError.code == "account_closed"
    assert AccountPausedError.code == "account_paused"
    assert AccountClosedError.code != AccountPausedError.code


def test_b61_a_size_without_recording_a_download() -> None:
    assert "/api/v1/lessons/{lesson_id}/offline-manifest" in SPEC["paths"]
    # A read, so it records nothing - the only size before this arrived with
    # the POST that records a download.
    assert "get" in SPEC["paths"]["/api/v1/lessons/{lesson_id}/offline-manifest"]
    manifest = SCHEMAS["OfflineManifestResponse"]["properties"]
    assert {"sizeBytes", "files", "includesMedia"} <= set(manifest)


def test_b65_only_one_warm_up_task_has_a_question() -> None:
    prompt = SCHEMAS["BaselinePromptResponse"]

    # Requiring question and options of every dimension made the five device
    # tasks look like served questions with nothing in them.
    assert set(prompt["required"]) == {"dimension", "itemId"}
    assert "served" in prompt["properties"]


def test_b64_a_looked_up_child_can_set_a_pin_and_get_a_session() -> None:
    # The lookup identifies the child and the entry link no longer exists, so
    # nothing bound the PIN chosen at the end of onboarding to the child found
    # at the start. This is that binding, and it was built for SCRUM-216.
    assert "/api/v1/student-entry/pin" in SPEC["paths"]
    setup = SCHEMAS["StudentPinSetup"]
    assert set(setup["required"]) == {"schoolCode", "admissionNumber", "pin"}
    # And it answers with a session, which is the half that makes it usable
    # as the last step of onboarding rather than only as a PIN reset.
    assert "StudentEntrySession" in SCHEMAS
    assert "session" in SCHEMAS["StudentEntrySession"]["properties"]
