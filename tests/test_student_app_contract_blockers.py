from nevo.api.lesson_contracts import checkpoint_payloads
from nevo.main import app


def test_onboarding_routes_are_pre_auth_and_use_json_contracts() -> None:
    schema = app.openapi()
    class_code = schema["paths"]["/api/v1/connections/class-code"]["post"]
    pin = schema["paths"]["/api/v1/auth/pin"]["post"]

    # Reachable without a session, which is what these two screens need. Not
    # "closed to one": both handlers take an optional principal and behave
    # differently signed in, so the declaration offers either and {} is the
    # part that says a signed-out caller is allowed.
    assert {} in class_code["security"]
    assert "requestBody" in class_code
    assert {} in pin["security"]
    # New PINs are exactly four digits. Unlock accepts the old six-digit shape
    # only long enough to return pinChangeRequired and migrate the learner.
    update_pin = schema["components"]["schemas"]["PinUpdateRequest"]["properties"]["pin"]
    login_pin = schema["components"]["schemas"]["PinLoginRequest"]["properties"]["pin"]
    assert (update_pin["minLength"], update_pin["maxLength"], update_pin["pattern"]) == (
        4,
        4,
        r"^\d+$",
    )
    assert login_pin["pattern"] == r"^(?:\d{4}|\d{6})$"


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
        # Ask Nevo had no session to report under, so its four event types
        # had nowhere to hang and a question asked outside a lesson was
        # invisible. Ask B15.
        "ask_nevo",
    ]


def test_lesson_variants_and_checkpoints_are_typed() -> None:
    """Asserted on the segment schemas a client is actually served.

    This used to check ParsedLessonSegmentResponse, which was only ever
    reachable through the synchronous parse response. That response is gone
    now the parse endpoints answer 202, so the guarantee has to be pinned to
    the lesson reads that carry segments to the student app.
    """
    schemas = app.openapi()["components"]["schemas"]
    served = [
        body["properties"]
        for name, body in schemas.items()
        if name.endswith("LessonSegmentResponse")
    ]

    assert served
    for properties in served:
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
    payload = checkpoint_payloads([{"prompt": "What changed?"}], segment_key="segment-2")[0]

    assert payload["id"] == "segment-2-check-1"
    assert payload["answerKey"] is None
    assert payload["answerType"] == "text"


def test_progress_and_review_navigation_fields_are_documented() -> None:
    schemas = app.openapi()["components"]["schemas"]

    assert {"reflection", "highlights"}.issubset(schemas["StudentProgressResponse"]["properties"])
    assert "lessonId" in schemas["ConceptScheduleResponse"]["properties"]
