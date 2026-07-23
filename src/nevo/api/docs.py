from fastapi.routing import APIRoute

API_DESCRIPTION = """
Nevo Backend 2.0 API.

This API powers authentication, school permissions, consent workflows, teacher
assignment management, signal ingestion, and AI Gateway-backed learning
workflows. The public contract uses functional learning language and avoids
clinical or diagnostic labels.
"""

OPENAPI_TAGS = [
    {
        "name": "authentication",
        "description": "Login, logout, and current session endpoints.",
    },
    {
        "name": "sso",
        "description": "Microsoft 365 and Google Workspace SSO and roster sync.",
    },
    {
        "name": "permissions",
        "description": "Admin team, role, scope, and navigation endpoints.",
    },
    {
        "name": "consent",
        "description": "School and parent consent collection workflows.",
    },
    {
        "name": "teacher assignments",
        "description": "Teacher-to-class assignment and roster sync workflows.",
    },
    {
        "name": "signals",
        "description": "High-throughput lesson session and signal ingestion.",
    },
    {
        "name": "ai-gateway",
        "description": "Centralized Gemini Gateway generation endpoint.",
    },
    {
        "name": "ask-nevo",
        "description": "Student and teacher Ask Nevo support assistant endpoints.",
    },
    {
        "name": "intelligence",
        "description": (
            "Adaptation, modality switching, proactive adjustment, and break "
            "threshold decisions."
        ),
    },
    {
        "name": "system",
        "description": "Operational health and platform status endpoints.",
    },
]

SWAGGER_UI_PARAMETERS = {
    "defaultModelsExpandDepth": 1,
    "displayRequestDuration": True,
    "filter": True,
    "persistAuthorization": True,
    "tryItOutEnabled": True,
}


def stable_operation_id(route: APIRoute) -> str:
    tag = route.tags[0] if route.tags else "default"
    normalized_tag = str(tag).replace(" ", "_").replace("-", "_")
    return f"{normalized_tag}_{route.name}"
