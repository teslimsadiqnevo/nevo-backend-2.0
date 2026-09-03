from nevo.api.lesson_contracts import checkpoint_payloads
from nevo.main import app


def test_onboarding_routes_are_pre_auth_and_use_json_contracts() -> None:
    schema = app.openapi()
    class_code = schema["paths"]["/api/v1/connections/class-code"]["post"]
    pin = schema["paths"]["/api/v1/auth/pin"]["post"]

    assert class_code["security"] == []
    assert "requestBody" in class_code
    assert pin["security"] == []
    assert schema["components"]["schemas"]["PinUpdateRequest"]["properties"]["pin"][
        "pattern"
    ] == r"^\d{6}$"
    assert schema["components"]["schemas"]["PinLoginRequest"]["properties"]["pin"][
        "pattern"
    ] == r"^\d{6}$"


def test_student_reply_and_non_lesson_signal_contracts_are_exposed() -> None:
    schema = app.openapi()
    assert "/api/messages/threads/{thread_id}/reply" in schema["paths"]
    session = schema["components"]["schemas"]["LessonSessionRequest"]

    assert "lessonId" not in session["required"]
    assert session["properties"]["sessionType"]["enum"] == [
        "lesson",
        "onboarding",
        "profiling",
        "sso",
    ]


def test_lesson_variants_and_checkpoints_are_typed() -> None:
    schema = app.openapi()
    segment = schema["components"]["schemas"]["ParsedLessonSegmentResponse"]
    properties = segment["properties"]
    for field, model in {
        "textVariant": "TextVariant",
        "visualVariant": "VisualVariant",
        "audioVariant": "AudioVariant",
        "interactiveVariant": "InteractiveVariant",
        "calculationVariant": "CalculationVariant",
    }.items():
        assert properties[field]["anyOf"][0]["$ref"].endswith(model)
    assert properties["comprehensionCheckpoints"]["items"]["$ref"].endswith(
        "ComprehensionCheckpoint"
    )


def test_legacy_checkpoint_is_normalized_without_inventing_an_answer() -> None:
    payload = checkpoint_payloads(
        [{"prompt": "What changed?"}], segment_key="segment-2"
    )[0]

    assert payload["id"] == "segment-2-check-1"
    assert payload["answerKey"] is None
    assert payload["answerType"] == "text"


def test_progress_and_review_navigation_fields_are_documented() -> None:
    schemas = app.openapi()["components"]["schemas"]

    assert {"reflection", "highlights"}.issubset(
        schemas["StudentProgressResponse"]["properties"]
    )
    assert "lessonId" in schemas["ConceptScheduleResponse"]["properties"]
