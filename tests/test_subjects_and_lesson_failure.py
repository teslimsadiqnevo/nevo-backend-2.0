"""What a teacher states, and what the library can say about a failure.

Subjects were derived only, from the subjects of lessons already assigned, so
a class with nothing assigned was blank and a teacher had no way to say what
it is taught. And a failed lesson carried its reason on the parse run, which
the library list does not have - so the card could not say why without a
request per row.
"""

from __future__ import annotations

from nevo.main import app


def test_subjects_are_stated_and_not_derived() -> None:
    """SCRUM-194 replaced the derived list with the class's own.

    Subjects used to be worked out from the subjects of lessons already
    assigned, so a class with nothing assigned read as having none - and a
    teacher had no way to say what it is taught. The derivation is gone.
    """

    import nevo.api.product_admin as admin

    assert not hasattr(admin, "_subjects_for")
    assert not hasattr(admin, "_class_subjects_bulk")


def test_normalising_folds_case_and_inner_spacing() -> None:
    from nevo.subjects.resolution import normalise

    # One school holding "Maths" and " maths " as two subjects is the thing
    # the uniqueness on normalised_name exists to stop.
    assert normalise("  Further   MATHS ") == "further maths"
    assert normalise("Mathematics") == normalise("mathematics")


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
