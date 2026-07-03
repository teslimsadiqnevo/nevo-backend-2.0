from fastapi import FastAPI
from fastapi.testclient import TestClient

from nevo.api.auth import authenticated_principal
from nevo.api.permissions import router
from nevo.domain.permissions.vocabulary import PermissionScope

from .test_service import principal_for, service_for, snapshot


def client_for_actor(*, scopes: frozenset[PermissionScope]):
    actor = snapshot(scopes=scopes)
    service, repository, _ = service_for(actor)
    app = FastAPI()
    app.state.permission_service = service
    app.dependency_overrides[authenticated_principal] = lambda: principal_for(actor)
    app.include_router(router)
    return TestClient(app), actor, repository


def test_my_permissions_returns_scopes_and_navigation() -> None:
    client, _, _ = client_for_actor(
        scopes=frozenset(
            {
                PermissionScope.SENCO,
                PermissionScope.CURRICULUM,
            }
        )
    )

    response = client.get("/api/v1/permissions/me")

    assert response.status_code == 200
    assert response.json()["scopes"] == ["curriculum", "senco"]
    assert response.json()["navigation"] == [
        "lessons",
        "curriculum",
        "students",
        "insights",
        "iep_exporter",
    ]


def test_team_endpoint_requires_oversight_scope() -> None:
    client, _, _ = client_for_actor(
        scopes=frozenset({PermissionScope.BILLING})
    )

    response = client.get("/api/v1/admin/team")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "permission_denied"


def test_invite_and_accept_flow() -> None:
    client, _, _ = client_for_actor(
        scopes=frozenset({PermissionScope.OVERSIGHT})
    )

    invited = client.post(
        "/api/v1/admin/team/invitations",
        json={
            "email": "teacher@example.com",
            "role": "teacher",
            "scopes": ["curriculum"],
        },
    )
    assert invited.status_code == 201
    assert invited.headers["Cache-Control"] == "no-store"
    invitation = invited.json()
    assert invitation["scopes"] == ["curriculum", "teacher"]

    accepted = client.post(
        "/api/v1/admin/team/invitations/accept",
        json={
            "invitation_token": invitation["invitation_token"],
            "password": "valid-password",
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["user_id"] == invitation["user_id"]


def test_student_role_cannot_be_invited() -> None:
    client, _, _ = client_for_actor(
        scopes=frozenset({PermissionScope.OVERSIGHT})
    )

    response = client.post(
        "/api/v1/admin/team/invitations",
        json={
            "email": "student@example.com",
            "role": "student",
            "scopes": ["roster"],
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_admin_role"


def test_scope_payload_rejects_unknown_scope() -> None:
    client, _, _ = client_for_actor(
        scopes=frozenset({PermissionScope.OVERSIGHT})
    )

    response = client.post(
        "/api/v1/admin/team/invitations",
        json={
            "email": "admin@example.com",
            "role": "other_admin",
            "scopes": ["superuser"],
        },
    )

    assert response.status_code == 422


def test_unknown_team_member_returns_404() -> None:
    client, _, _ = client_for_actor(
        scopes=frozenset({PermissionScope.OVERSIGHT})
    )

    response = client.put(
        "/api/v1/admin/team/00000000-0000-0000-0000-000000000099/scopes",
        json={"scopes": ["billing"]},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "team_member_not_found"


def test_invitation_token_is_one_time_use() -> None:
    client, _, _ = client_for_actor(
        scopes=frozenset({PermissionScope.OVERSIGHT})
    )
    invitation = client.post(
        "/api/v1/admin/team/invitations",
        json={
            "email": "admin@example.com",
            "role": "other_admin",
            "scopes": ["billing"],
        },
    ).json()
    payload = {
        "invitation_token": invitation["invitation_token"],
        "password": "valid-password",
    }

    assert (
        client.post(
            "/api/v1/admin/team/invitations/accept",
            json=payload,
        ).status_code
        == 200
    )
    second = client.post(
        "/api/v1/admin/team/invitations/accept",
        json=payload,
    )
    assert second.status_code == 400
    assert second.json()["detail"]["code"] == "invalid_invitation"
