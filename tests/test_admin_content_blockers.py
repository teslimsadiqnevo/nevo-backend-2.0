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
