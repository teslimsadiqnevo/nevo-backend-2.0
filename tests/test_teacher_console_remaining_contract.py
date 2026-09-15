from pathlib import Path

from nevo.main import app


def test_teacher_console_routes_and_shapes_are_typed() -> None:
    spec = app.openapi()
    paths = spec["paths"]
    schemas = spec["components"]["schemas"]

    assert paths["/api/v1/escalations"]["post"]["responses"]["201"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("/EscalationResponse")
    assert paths["/api/v1/students/{student_id}/sessions/{session_id}"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/StudentSessionDetailResponse"
    )
    assert paths["/api/v1/classes/{class_id}/insights"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]["$ref"].endswith("/ClassInsightsNarrativeResponse")

    assert {"weeklySummary", "lookingAhead"} <= set(
        schemas["ClassInsightsNarrativeResponse"]["properties"]
    )
    assert {"narrative", "sittings", "sections"} <= set(
        schemas["StudentSessionDetailResponse"]["properties"]
    )
    assert {"completedCount", "totalCount"} <= set(
        schemas["TeacherRecentActivityResponse"]["properties"]
    )


def test_existing_contracts_carry_the_new_fields() -> None:
    spec = app.openapi()
    paths = spec["paths"]
    schemas = spec["components"]["schemas"]

    assert "slug" in schemas["SchoolCodeResponse"]["properties"]
    assert "note" in schemas["AssignmentCreate"]["properties"]
    assert "note" in schemas["LessonAssignmentRequest"]["properties"]
    assert "note" in schemas["AssignmentResponse"]["properties"]
    assert "failedPages" in schemas["UploadStatusResponse"]["properties"]
    assert "profileImageUrl" in schemas["ProfilePatch"]["properties"]
    assert "/api/v1/users/me/profile-photo" in paths

    upload_body = paths["/api/content/upload"]["post"]["requestBody"]["content"]
    multipart_schema = upload_body["multipart/form-data"]["schema"]["$ref"].rsplit("/", 1)[-1]
    assert "subject" in schemas[multipart_schema]["properties"]
    assert "404" in paths["/api/v1/consents/parent/{token}"]["get"]["responses"]


def test_assignment_note_migration_is_chained_to_head() -> None:
    migration = Path("alembic/versions/20260915_0055_teacher_console_gaps.py").read_text()
    assert 'down_revision: str | Sequence[str] | None = "20260911_0054"' in migration
    assert 'op.add_column("lesson_assignments"' in migration
    assert 'sa.Column("note", sa.Text(), nullable=True)' in migration
