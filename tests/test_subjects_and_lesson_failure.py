"""What a teacher states, and what the library can say about a failure.

Subjects were derived only, from the subjects of lessons already assigned, so
a class with nothing assigned was blank and a teacher had no way to say what
it is taught. And a failed lesson carried its reason on the parse run, which
the library list does not have - so the card could not say why without a
request per row.
"""

from __future__ import annotations

from nevo.api.product_admin import _subjects_for
from nevo.main import app

DERIVED = ["Basic Science", "Mathematics"]


def test_nothing_stated_falls_back_to_what_was_derived() -> None:
    # Today's behaviour, and the only thing a class with no assignments can do.
    assert _subjects_for([], DERIVED) == DERIVED
    assert _subjects_for(None, DERIVED) == DERIVED


def test_stated_replaces_derived_rather_than_merging() -> None:
    # A teacher who writes a list and still sees a subject they did not write
    # has no way to remove it, so merging would be lying about the control.
    assert _subjects_for(["English"], DERIVED) == ["English"]
    assert "Mathematics" not in _subjects_for(["English"], DERIVED)


def test_a_stated_list_is_tidied_but_not_second_guessed() -> None:
    assert _subjects_for(["  English  ", "English", ""], DERIVED) == ["English"]
    # Whitespace-only is not a statement, so it falls back.
    assert _subjects_for(["   "], DERIVED) == DERIVED


def test_a_teacher_can_send_one_and_take_it_back() -> None:
    write = app.openapi()["components"]["schemas"]["ClassWrite"]["properties"]["subjects"]

    # Nullable: absent means "no change", [] means "go back to deriving".
    assert any(arm.get("type") == "null" for arm in write["anyOf"])


def test_a_failed_lesson_carries_its_own_reason() -> None:
    summary = app.openapi()["components"]["schemas"]["LessonSummaryResponse"]["properties"]

    assert "failureReason" in summary
    assert "incidentId" in summary


def test_the_reason_is_written_onto_the_lesson_when_the_run_fails() -> None:
    import inspect

    from nevo.content_parsing.repositories import SqlAlchemyContentParsingRepository

    source = inspect.getsource(SqlAlchemyContentParsingRepository.fail_run)

    assert "lesson.failure_reason = failure_reason" in source
    assert "lesson.incident_id = incident_id" in source


def test_lesson_detail_names_every_class_it_reached() -> None:
    detail = app.openapi()["components"]["schemas"]["LessonDetailResponse"]["properties"]

    # assignmentCount is a number; the screen shows all of them.
    assert "classes" in detail
    assert "assignmentCount" in detail


def test_the_break_thresholds_are_named_on_the_wire() -> None:
    """Typed because a bare array of strings cost three rounds of asking."""

    schemas = app.openapi()["components"]["schemas"]

    assert schemas["BreakThreshold"]["enum"] == [
        "time_threshold",
        "engagement_decline",
        "comprehension_drop",
        "repeated_errors",
        "replay_accumulation",
    ]
    # mild, not low: the code has always emitted mild and nobody could see it.
    assert schemas["BreakSeverity"]["enum"] == ["none", "mild", "medium", "high"]
    thresholds = schemas["BreakSuggestionResponse"]["properties"]["triggeredThresholds"]
    assert thresholds["items"]["$ref"].endswith("/BreakThreshold")
