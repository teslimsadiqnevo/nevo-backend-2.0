from fastapi.testclient import TestClient

from nevo.main import app


def test_swagger_and_openapi_endpoints_are_wired() -> None:
    assert app.docs_url == "/docs"
    assert app.redoc_url == "/redoc"
    assert app.openapi_url == "/openapi.json"


def test_local_frontend_origin_can_preflight_api_requests() -> None:
    response = TestClient(app).options(
        "/api/v1/auth/login/password",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_openapi_schema_documents_existing_api_groups() -> None:
    schema = app.openapi()

    assert schema["info"]["title"] == "Nevo Backend API"
    assert schema["info"]["version"] == "2.0.0"
    tag_names = {tag["name"] for tag in schema["tags"]}
    assert {
        "authentication",
        "sso",
        "permissions",
        "admin",
        "billing",
        "consent",
        "teacher assignments",
        "signals",
        "content",
        "ai-gateway",
        "ask-nevo",
        "exports",
        "intelligence",
        "mastery",
        "scheduler",
        "system",
    }.issubset(tag_names)

    assert "/health" in schema["paths"]
    assert "/api/v1/auth/login/password" in schema["paths"]
    assert "/api/admin/adaptation-log" in schema["paths"]
    assert "/api/admin/compliance-audit" in schema["paths"]
    assert "/api/admin/compliance-audit/scan" in schema["paths"]
    assert "/api/admin/compliance-audit/report.pdf" in schema["paths"]
    assert "/api/billing/subscription" in schema["paths"]
    assert "/api/billing/invoices" in schema["paths"]
    assert "/api/billing/upcoming" in schema["paths"]
    assert "/api/billing/payment-method" in schema["paths"]
    assert "/api/billing/billing-contact" in schema["paths"]
    assert "/api/v1/ask-nevo/" in schema["paths"]
    assert "/api/v1/exports/iep" in schema["paths"]
    assert "/api/v1/auth/sso/{provider}/callback" in schema["paths"]
    assert "/api/signals/" in schema["paths"]
    assert "/api/content/parse" in schema["paths"]
    assert "/api/intelligence/adapt" in schema["paths"]
    assert "/api/mastery/update" in schema["paths"]
    assert "/api/mastery/student/{student_id}" in schema["paths"]
    assert "/api/mastery/class/{class_id}" in schema["paths"]
    assert "/api/mastery/school/{school_id}" in schema["paths"]
    assert "/api/scheduler/due-reviews/{student_id}" in schema["paths"]
    assert "/api/scheduler/record-review" in schema["paths"]
    assert "/api/intelligence/accommodations/{student_id}" in schema["paths"]
    assert "/api/intelligence/scaffolds/state/{student_id}/{concept_id}" in schema["paths"]
    assert "/api/intelligence/scaffolds/attempt" in schema["paths"]
    assert "/api/intelligence/scaffolds/history/{student_id}" in schema["paths"]
    assert (
        schema["paths"]["/api/signals/"]["post"]["operationId"]
        == "signals_ingest_signal_batch"
    )
