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
            "202",
            "ParseAcceptedResponse",
        ),
        ("/api/content/parse", "post", "202", "ParseAcceptedResponse"),
        ("/api/content/parse-runs/{parse_run_id}", "get", "200", "ParseRunResponse"),
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
        # An account is created by verifying a code now, not by setting a
        # password, so the setup endpoint is the code pair.
        "/api/v1/auth/parent/request-code",
        "/api/v1/auth/parent/verify-code",
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


def test_a_parse_run_id_is_something_a_client_can_use() -> None:
    """It was returned by two endpoints and accepted as a parameter by none."""
    spec = app.openapi()
    run_id_params = [
        f"{method.upper()} {path}"
        for path, operations in spec["paths"].items()
        for method, operation in operations.items()
        for parameter in operation.get("parameters", [])
        if parameter["name"] == "parse_run_id"
    ]

    assert run_id_params, "nothing in the contract takes a parse run id"


def test_generation_endpoints_declare_the_refusals_they_actually_make() -> None:
    """A 403 was reachable on these and documented on none of them."""
    paths = app.openapi()["paths"]

    for path in ("/api/content/parse", "/api/content/lessons/{lesson_id}/regenerate"):
        assert "403" in paths[path]["post"]["responses"], path


def test_a_lesson_list_says_who_wrote_each_lesson() -> None:
    """Without it a dashboard cannot tell its own teacher's work from the
    rest of the school's, even after fetching the list."""
    schemas = app.openapi()["components"]["schemas"]
    # Two classes still share this name, so the spec namespaces them. Both
    # are served, so both have to carry the author.
    summaries = [
        body["properties"]
        for name, body in schemas.items()
        if name.endswith("LessonSummaryResponse")
    ]

    assert summaries
    for summary in summaries:
        assert "createdById" in summary
        assert "createdByName" in summary
    assert schemas["LessonScope"]["enum"] == ["mine", "school"]


def test_both_lesson_listings_take_the_same_scope() -> None:
    """They used to disagree about what a teacher could see."""
    paths = app.openapi()["paths"]

    for path in ("/api/v1/lessons", "/api/content/lessons"):
        names = {p["name"] for p in paths[path]["get"].get("parameters", [])}
        assert "scope" in names, path


def test_no_content_endpoint_still_parses_inside_the_request() -> None:
    """Every route that starts a parse answers immediately.

    An upload that holds the request open for minutes of model work is a
    request every proxy in front of it hangs up on first.
    """
    paths = app.openapi()["paths"]

    for path in (
        "/api/content/parse",
        "/api/content/upload",
        "/api/content/lessons/{lesson_id}/regenerate",
    ):
        assert "202" in paths[path]["post"]["responses"], path
        assert "200" not in paths[path]["post"]["responses"], path

    # The staged upload routes answer 201 with a job to poll instead.
    for path in ("/api/v1/uploads", "/api/v1/uploads/text", "/api/v1/uploads/import"):
        assert "201" in paths[path]["post"]["responses"], path
    assert "/api/v1/uploads/{upload_id}" in paths


def test_no_endpoint_walks_a_provider_inside_the_request() -> None:
    """A roster sync pages every class and every member through the
    provider's API, with no cap. That is not a request to hold open."""
    paths = app.openapi()["paths"]

    sync = paths["/api/v1/admin/sso/roster-sync"]["post"]["responses"]
    assert "202" in sync
    assert "200" not in sync
    assert "/api/v1/admin/sso/roster-sync/{run_id}" in paths


def test_a_sync_can_report_that_it_is_still_running() -> None:
    """The run row was only written once the walk finished, so a sync in
    progress was indistinguishable from one that had died."""
    statuses = app.openapi()["components"]["schemas"]["RosterSyncStatus"]["enum"]

    assert "running" in statuses


def test_the_roster_sync_shapes_speak_the_same_case_as_everything_else() -> None:
    """These were the only new surface still emitting snake_case."""
    schemas = app.openapi()["components"]["schemas"]

    for name in (
        "RosterSyncRunResponse",
        "RosterSyncIssueResponse",
        "RosterSyncHistoryResponse",
        "RosterSyncAcceptedResponse",
    ):
        for field in schemas[name]["properties"]:
            assert "_" not in field, f"{name}.{field}"


def test_parent_auth_is_a_code_not_a_password() -> None:
    """Design ruled email plus code. The password flow is gone, not deprecated."""
    paths = app.openapi()["paths"]
    schemas = app.openapi()["components"]["schemas"]

    assert "/api/v1/auth/parent/request-code" in paths
    assert "/api/v1/auth/parent/verify-code" in paths
    assert "/api/v1/auth/login/parent" not in paths
    assert "/api/v1/consents/parent/{token}/account" not in paths

    # Nothing on the parent path takes a password any more.
    for name in ("ParentCodeRequest", "ParentCodeVerifyRequest"):
        assert "password" not in schemas[name]["properties"]


def test_requesting_a_code_never_says_whether_the_contact_is_known() -> None:
    """This surface is tied to named children, so confirming an address is
    known is a way to find out which families use Nevo."""
    request_code = app.openapi()["paths"]["/api/v1/auth/parent/request-code"]["post"]

    assert list(request_code["responses"]) == ["202", "422"]
    assert "404" not in request_code["responses"]


def test_the_setup_screen_can_prefill_the_contact_the_school_holds() -> None:
    invitation = app.openapi()["components"]["schemas"][
        "ParentConsentInvitationResponse"
    ]["properties"]

    assert "parentContact" in invitation
    assert "parentContactMethod" in invitation


def test_a_session_ending_says_how_it_ended() -> None:
    """Revoked, paused and timed out are three different screens. They used to
    collapse into one invalid_session."""
    from nevo.auth.errors import (
        AccountPausedError,
        SessionExpiredError,
        SessionReplacedError,
        SessionRevokedError,
    )

    codes = {
        SessionExpiredError.code,
        SessionRevokedError.code,
        SessionReplacedError.code,
        AccountPausedError.code,
    }

    assert codes == {
        "session_expired",
        "session_revoked",
        "session_replaced",
        "account_paused",
    }


def test_both_settings_paths_merge_rather_than_replace() -> None:
    """They wrote to the same column with different rules: one merged, the
    other replaced. A client using the replacing one erased every key the
    other had set."""
    from nevo.api.product_admin import merge_preferences

    stored = {"theme": "dark", "reduceMotion": True}

    assert merge_preferences(stored, {"theme": "light"}) == {
        "theme": "light",
        "reduceMotion": True,
    }
    # Null removes a key, which is the only way to delete one under a merge.
    assert merge_preferences(stored, {"reduceMotion": None}) == {"theme": "dark"}
    # And an empty write changes nothing.
    assert merge_preferences(stored, {}) == stored


def test_the_older_settings_path_is_marked_superseded() -> None:
    paths = app.openapi()["paths"]

    for method in ("get", "put"):
        assert paths["/api/settings/me"][method]["deprecated"] is True
        assert "deprecated" not in paths["/api/v1/settings/me"][method]
