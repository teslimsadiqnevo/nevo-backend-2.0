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
