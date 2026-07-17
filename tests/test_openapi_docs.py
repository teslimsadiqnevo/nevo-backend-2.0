from nevo.main import app


def test_swagger_and_openapi_endpoints_are_wired() -> None:
    assert app.docs_url == "/docs"
    assert app.redoc_url == "/redoc"
    assert app.openapi_url == "/openapi.json"


def test_openapi_schema_documents_existing_api_groups() -> None:
    schema = app.openapi()

    assert schema["info"]["title"] == "Nevo Backend API"
    assert schema["info"]["version"] == "2.0.0"
    tag_names = {tag["name"] for tag in schema["tags"]}
    assert {
        "authentication",
        "permissions",
        "consent",
        "teacher assignments",
        "signals",
        "ai-gateway",
        "intelligence",
        "system",
    }.issubset(tag_names)

    assert "/health" in schema["paths"]
    assert "/api/v1/auth/login/password" in schema["paths"]
    assert "/api/signals/" in schema["paths"]
    assert "/api/intelligence/adapt" in schema["paths"]
    assert (
        schema["paths"]["/api/signals/"]["post"]["operationId"]
        == "signals_ingest_signal_batch"
    )
