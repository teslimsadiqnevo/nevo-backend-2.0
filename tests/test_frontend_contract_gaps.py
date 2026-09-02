"""Contract-level guards for the gaps the console reported.

Each test pins a read-side promise to the write path that can now fulfil it,
so a required field cannot silently go back to having no way to change it.
"""
from nevo.db.base import Base
from nevo.domain.accounts.vocabulary import NotificationCategory
from nevo.domain.intelligence.vocabulary import (
    SegmentReviewReason,
    UploadStage,
    UploadStatus,
)
from nevo.main import app


def operations() -> set[tuple[str, str]]:
    spec = app.openapi()
    return {
        (method.upper(), path)
        for path, item in spec["paths"].items()
        for method in item
        if method in {"get", "post", "put", "patch", "delete"}
    }


def schema(name: str) -> dict:
    return app.openapi()["components"]["schemas"][name]


def test_an_unread_thread_can_be_marked_read() -> None:
    assert ("POST", "/api/messages/threads/{thread_id}/read") in operations()


def test_an_unacknowledged_flag_can_be_acknowledged() -> None:
    assert ("POST", "/api/intelligence/flags/{flag_id}/acknowledge") in operations()


def test_a_profile_can_be_written_not_only_read() -> None:
    ops = operations()
    assert ("GET", "/api/v1/users/me") in ops
    assert ("PATCH", "/api/v1/users/me") in ops


def test_archived_notifications_can_be_listed() -> None:
    spec = app.openapi()["paths"]["/api/notifications"]["get"]
    assert "archived" in {p["name"] for p in spec.get("parameters", [])}


def test_a_notification_reports_whether_it_is_archived() -> None:
    assert "archived" in schema("NotificationResponse")["properties"]


def test_several_files_can_be_uploaded_at_once() -> None:
    assert ("POST", "/api/v1/uploads/batch") in operations()


def test_a_batch_reports_each_file_separately() -> None:
    """One bad file must not sink the batch."""
    properties = schema("BatchUploadItemResponse")["properties"]
    assert {"filename", "accepted", "error"} <= set(properties)


def test_an_upload_can_produce_several_lessons() -> None:
    structure = schema("UploadStructureDocument")["properties"]
    assert "lessons" in structure
    # The single-lesson shape stays so existing clients keep working.
    assert "lessonId" in structure
    assert "modules" in structure


def test_assignment_creation_reports_duplicates_rather_than_erroring() -> None:
    assert "duplicateCount" in schema("AssignmentCreatedResponse")["properties"]


def test_assignments_cannot_be_duplicated_by_a_retry() -> None:
    index = next(
        item
        for item in Base.metadata.tables["lesson_assignments"].indexes
        if item.name == "uq_lesson_assignments_lesson_student_release"
    )
    assert index.unique
    assert [column.name for column in index.columns] == [
        "lesson_id",
        "student_id",
        "available_from",
    ]
    # NULL available_from must collide with itself, or an unscheduled
    # assignment could still be duplicated freely.
    assert index.dialect_options["postgresql"]["nulls_not_distinct"]


def test_review_reasons_are_enumerated() -> None:
    reasons = schema("SegmentReviewReason")["enum"]

    assert set(reasons) == {item.value for item in SegmentReviewReason}
    assert "fewer_than_two_modalities" in reasons


def test_upload_status_and_stage_are_enumerated() -> None:
    assert set(schema("UploadStatus")["enum"]) == {item.value for item in UploadStatus}
    assert set(schema("UploadStage")["enum"]) == {item.value for item in UploadStage}


def test_a_preference_category_typo_is_reported_not_silently_stored() -> None:
    """Rejected per row, not by failing the batch.

    The request field is deliberately a plain string so an unknown category
    reaches the handler. Typing it in the schema made Pydantic reject the whole
    list before any row was written, so one unrecognised category discarded a
    user's other valid changes.
    """
    assert schema("PreferenceWrite")["properties"]["category"]["type"] == "string"

    write = schema("NotificationPreferencesWriteResponse")["properties"]
    assert {"preferences", "savedCount", "rejected"} <= set(write)
    # The response is still typed, so the vocabulary is discoverable.
    assert "$ref" in str(schema("NotificationPreferenceResponse")["properties"]["category"])
    assert "account" in {item.value for item in NotificationCategory}


def test_segments_and_lessons_both_report_a_duration() -> None:
    """Both the parse-review and the lesson-read shapes carry minutes.

    The name is duplicated across two modules, so the spec namespaces it. Every
    variant has to carry the field or one of the two screens still has no
    source for its minute totals.
    """
    schemas = app.openapi()["components"]["schemas"]
    segment_shapes = [
        name for name in schemas if name.endswith(("LessonSegmentResponse",))
    ]
    lesson_shapes = [name for name in schemas if name.endswith(("LessonSummaryResponse",))]

    assert segment_shapes and lesson_shapes
    for name in segment_shapes + lesson_shapes:
        assert "estimatedMinutes" in schemas[name]["properties"], name


def test_a_new_lesson_in_a_split_needs_no_client_minted_id() -> None:
    """Split was unbuildable while lessonId was required.

    A client had to invent a UUID for a row it does not own, and confirm then
    discarded it and minted its own - so the write was accepted and the id was
    silently not the one that existed.
    """
    lesson = schema("UploadLessonDocument")

    assert "lessonId" not in lesson.get("required", [])
    assert "title" in lesson["required"]


def test_confirm_returns_every_lesson_id_it_created() -> None:
    """Positionally aligned with lessons[], so a new lesson can be matched."""
    assert "lessonIds" in schema("UploadConfirmedResponse")["properties"]


def test_upload_status_names_its_segments() -> None:
    """Otherwise the third review level is a count, not named rows."""
    status = schema("UploadStatusResponse")["properties"]

    assert "segments" in status
    assert "lessonTitle" in status
    segment = schema("UploadSegmentDocument")["properties"]
    assert {"segmentKey", "title", "contentType"} <= set(segment)


def test_roster_observations_are_a_closed_vocabulary() -> None:
    """An untyped string[] gave a client no way to know the contents were
    closed rather than free text, which is a fair reason to refuse to render
    it. The guarantee now lives in the schema."""
    observations = schema("ClassStudentResponse")["properties"]["observations"]

    assert "LearnerObservationResponse" in str(observations)
    assert schema("LearnerObservationPattern")["enum"]
    # The client composes the wording; the backend only says which pattern.
    assert set(schema("LearnerObservationResponse")["properties"]) == {"pattern", "count"}


def test_bulk_writes_are_bounded() -> None:
    """An unbounded list is an unbounded amount of work per request."""
    spec = app.openapi()["components"]["schemas"]

    assert spec["LessonAssignmentRequest"]["properties"]["studentIds"]["maxItems"] == 500
    # Its sibling endpoint was already bounded; these two must not disagree.
    assert spec["AssignmentCreate"]["properties"]["studentIds"]["maxItems"] == 500


def test_listing_classes_does_not_scale_queries_with_classes() -> None:
    """It ran two queries per class on a page every admin opens."""
    import inspect

    from nevo.api import product_admin

    body = inspect.getsource(product_admin.list_classes)

    assert "_student_counts" in body
    assert "_class_subjects_bulk" in body
    # The per-class helpers must not be called from inside the loop.
    assert "await _class_subjects(" not in body


def test_saving_preferences_reads_existing_rows_once() -> None:
    import inspect

    from nevo.api import product_admin

    body = inspect.getsource(product_admin.update_notification_preferences)

    assert "existing = {" in body
    assert "existing.get(category)" in body
