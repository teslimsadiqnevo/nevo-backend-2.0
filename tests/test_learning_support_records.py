"""What Nevo did, dated - and whose words are whose on the document.

The rule from the counsel document runs through both: the system records what
the software did, never what the child is. No score, index, rating or
forecast is stored or exposed by either of these.
"""

from __future__ import annotations

import inspect

import pytest

from nevo.api import learning_support_records
from nevo.api.learning_support_records import ADAPTATION_EVENTS, add_annotation
from nevo.db.models.learning_support import AccommodationChange, ExportAnnotation
from nevo.domain.learning_support.vocabulary import (
    AccommodationChangeAction,
    AnnotationOrigin,
)
from nevo.main import app


@pytest.fixture(scope="module")
def spec() -> dict:
    return app.openapi()


def test_a_staff_note_carries_a_named_author_and_a_time() -> None:
    columns = {column.name for column in ExportAnnotation.__table__.columns}

    assert {"author_user_id", "author_name", "author_role", "created_at", "body"} <= columns


def test_the_author_and_the_time_are_not_taken_from_the_caller(spec: dict) -> None:
    fields = set(spec["components"]["schemas"]["AnnotationWrite"]["properties"])

    # A note that says whatever the caller claimed about who wrote it is not
    # a record of anything.
    assert fields == {"body"}
    source = inspect.getsource(add_annotation)
    assert "author_user_id=actor.id" in source


def test_a_reader_can_tell_nevos_words_from_the_schools(spec: dict) -> None:
    composition = spec["components"]["schemas"]["ExportComposition"]["properties"]

    # Nevo's text and the school's notes come back as separate things, so a
    # renderer never has to decide which is which.
    assert {"nevoText", "annotations", "reviewNote"} <= set(composition)
    assert [origin.value for origin in AnnotationOrigin] == ["nevo", "school_staff"]


def test_the_approval_note_is_kept_apart_from_the_annotations(spec: dict) -> None:
    composition = spec["components"]["schemas"]["ExportComposition"]["properties"]

    # Approving a document and annotating it are different acts.
    assert {"reviewNote", "reviewedBy", "reviewedAt", "status"} <= set(composition)


def test_an_accommodation_change_says_when_and_what_prompted_it() -> None:
    columns = {column.name for column in AccommodationChange.__table__.columns}

    assert {"accommodation", "action", "prompted_by", "occurred_at"} <= columns
    assert [action.value for action in AccommodationChangeAction] == ["added", "removed"]


def test_nothing_is_written_when_nothing_changed() -> None:
    source = inspect.getsource(learning_support_records.record_accommodation_changes)

    # Set difference both ways: a set that has not moved writes no rows.
    assert "active - previous" in source
    assert "previous - active" in source


def test_the_log_is_its_own_source_of_truth() -> None:
    source = inspect.getsource(learning_support_records._current_accommodations)

    # Holding "what is in force now" somewhere else would give two answers
    # that can disagree.
    assert "row_number" in source


def test_the_change_is_recorded_where_it_is_decided() -> None:
    from nevo.api.intelligence import analyse_accommodations

    source = inspect.getsource(analyse_accommodations)

    assert "record_accommodation_changes" in source


def test_weekly_counts_are_raw(spec: dict) -> None:
    history = spec["components"]["schemas"]["AccommodationHistory"]["properties"]

    assert "adaptationsPerWeek" in history
    source = inspect.getsource(learning_support_records.read_accommodation_history)
    # No smoothing and no projection: the week something changed is the only
    # week anybody opens this for.
    assert "avg" not in source.lower()
    assert "forecast" not in source.lower()


def test_the_counted_events_are_adaptations_not_judgements() -> None:
    names = {event.value for event in ADAPTATION_EVENTS}

    assert "simplify_trigger" in names
    assert all("score" not in name and "level" not in name for name in names)


def test_the_history_exposes_no_score_or_index(spec: dict) -> None:
    history = spec["components"]["schemas"]["AccommodationHistory"]["properties"]

    assert not any(
        word in field.lower()
        for field in history
        for word in ("score", "index", "rating", "forecast")
    )
