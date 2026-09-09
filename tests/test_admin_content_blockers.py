from nevo.main import app


def test_admin_and_content_blocker_routes_are_typed() -> None:
    paths = app.openapi()["paths"]

    expected = {
        ("/api/v1/schools/register", "post", "201", "SchoolRegistrationResponse"),
        ("/api/v1/auth/session/refresh", "post", "200", "SessionResponse"),
        ("/api/v1/school/narrative", "get", "200", "SchoolNarrativeResponse"),
        ("/api/v1/school/dpa-acceptance", "post", "201", "DpaAcceptanceResponse"),
        (
            "/api/content/lessons/{lesson_id}/regenerate",
            "post",
            "200",
            "ParseContentResponse",
        ),
    }
    for path, method, status, schema_name in expected:
        schema = paths[path][method]["responses"][status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith(f"/{schema_name}")


def test_validation_error_contract_matches_runtime_envelope() -> None:
    schema = app.openapi()["components"]["schemas"]["HTTPValidationError"]

    assert schema["required"] == ["detail"]
    assert schema["properties"]["detail"]["required"] == [
        "code",
        "message",
        "errors",
    ]


def test_student_contracts_include_consent_audit_summary() -> None:
    schemas = app.openapi()["components"]["schemas"]

    for name in ("StudentSummaryResponse", "StudentDetailResponse", "ClassStudentResponse"):
        assert "consent" in schemas[name]["required"]
        assert schemas[name]["properties"]["consent"]["$ref"].endswith(
            "/StudentConsentSummaryResponse"
        )


def test_calculation_is_a_native_segment_type() -> None:
    values = app.openapi()["components"]["schemas"]["LessonContentType"]["enum"]

    assert "calculation" in values


def test_parent_consent_screen_contracts_are_typed() -> None:
    spec = app.openapi()
    paths, schemas = spec["paths"], spec["components"]["schemas"]

    read = paths["/api/v1/consents/parent/{token}"]["get"]["responses"]["200"]
    assert read["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ParentConsentInvitationResponse"
    )
    invitation = schemas["ParentConsentInvitationResponse"]["properties"]
    for field in ("studentFirstName", "schoolName", "schoolPhone", "schoolEmail"):
        assert field in invitation

    # A generated client should not have to discover these by sending a bad one.
    request_type = schemas["ParentRightRequest"]["properties"]["requestType"]
    assert schemas["ParentRightType"]["enum"] == [
        "request_data",
        "object",
        "withdraw_consent",
    ]
    assert "reason" in schemas["ParentRightRequest"]["properties"]
    assert "$ref" in request_type or "allOf" in request_type


def test_consent_gate_can_report_a_withdrawal() -> None:
    schemas = app.openapi()["components"]["schemas"]

    assert schemas["ConsentStatus"]["enum"] == [
        "not_sent",
        "pending",
        "confirmed",
        "withdrawn",
    ]
    assert schemas["ConsentGateResponse"]["properties"]["status"]


def test_the_parent_surface_is_in_the_contract() -> None:
    spec = app.openapi()
    paths, schemas = spec["paths"], spec["components"]["schemas"]

    for path in (
        "/api/v1/parents/me/children",
        "/api/v1/parents/me/children/{student_id}/growth",
        "/api/v1/consents/parent/{token}/account",
    ):
        assert path in paths, path

    # The declared invite roles are the ones the flow actually creates. It
    # used to advertise five and accept two.
    assert schemas["InvitableRole"]["enum"] == ["student", "teacher"]

    growth = schemas["GrowthNarrativeResponse"]["properties"]
    assert schemas["GrowthDimension"]["enum"] == [
        "staying_with_hard_problems",
        "knowing_what_she_knows",
        "connecting_ideas",
        "learning_new_things_faster",
    ]
    assert schemas["GrowthTrend"]["enum"] == [
        "growing",
        "steady",
        "emerging",
        "not_enough_yet",
    ]
    # Provenance, so the page can say when it was written.
    for field in ("generatedAt", "source", "periodStart", "comparisonStart"):
        assert field in growth
    # And nothing countable anywhere in the payload.
    statement = schemas["GrowthStatementResponse"]["properties"]
    assert set(statement) == {"dimension", "trend", "statement"}


def test_consent_completion_reports_the_copy_it_sent() -> None:
    completion = app.openapi()["components"]["schemas"][
        "ParentConsentCompletionResponse"
    ]["properties"]

    assert "receipt_sent_to" in completion
