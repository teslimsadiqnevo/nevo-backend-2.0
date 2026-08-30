from nevo.main import app


def test_design_contract_routes_are_documented() -> None:
    paths = app.openapi()["paths"]
    required = {
        "/api/v1/auth/pin/reset",
        "/api/v1/auth/password-reset/complete",
        "/api/v1/auth/sessions",
        "/api/v1/invites",
        "/api/v1/join/{token}/accept",
        "/api/v1/school",
        "/api/v1/classes",
        "/api/v1/teachers",
        "/api/v1/students",
        "/api/v1/lessons",
        "/api/v1/assignments",
        "/api/v1/lessons/{lesson_id}/session",
        "/api/v1/lessons/{lesson_id}/progress",
        "/api/v1/students/me/dashboard",
        "/api/v1/teachers/me/dashboard",
        "/api/v1/uploads",
        "/api/v1/notifications/unread-exists",
        "/api/v1/notification-preferences",
        "/api/v1/feedback",
        "/api/v1/ops/overview",
    }

    assert required <= set(paths)


def test_notification_contract_uses_boolean_unread_state() -> None:
    operation = app.openapi()["paths"]["/api/v1/notifications/unread-exists"]["get"]
    response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]

    assert response_schema["additionalProperties"]["type"] == "boolean"
