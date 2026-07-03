from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nevo.api.auth import authenticated_principal
from nevo.api.permissions import get_permission_service
from nevo.api.teacher_assignments import router
from nevo.auth.entities import AuthPrincipal
from nevo.domain.permissions.vocabulary import PermissionScope
from nevo.domain.teacher_assignments.vocabulary import (
    TeacherAssignmentRole,
    TeacherAssignmentSource,
)
from nevo.permissions.entities import PermissionSnapshot
from nevo.permissions.security import HmacInvitationTokenService
from nevo.permissions.service import PermissionService
from nevo.teacher_assignments.entities import (
    RosterAssignmentBatch,
    TeacherClassAssignment,
)
from nevo.teacher_assignments.service import TeacherAssignmentService

from .fakes import (
    FakeRosterAssignmentProvider,
    MemoryTeacherAssignmentRepository,
)
from .test_service import Clock


class PermissionRepository:
    def __init__(self, snapshot: PermissionSnapshot) -> None:
        self.current = snapshot

    async def snapshot(self, user_id: UUID) -> PermissionSnapshot | None:
        return self.current if self.current.user_id == user_id else None


class PasswordHasher:
    @staticmethod
    def hash_password(password: str) -> str:
        return f"hash:{password}"


def client_for(
    *,
    role: str = "other_admin",
    scopes: frozenset[PermissionScope],
):
    actor = PermissionSnapshot(
        user_id=uuid4(),
        school_id=uuid4(),
        role=role,
        status="active",
        school_auth_method="email_password",
        assigned_scopes=scopes,
    )
    principal = AuthPrincipal(
        user_id=actor.user_id,
        role=actor.role,
        session_id=uuid4(),
    )
    permissions = PermissionService(
        repository=PermissionRepository(actor),
        invitation_tokens=HmacInvitationTokenService("x" * 40),
        password_hasher=PasswordHasher(),
    )
    assignment_repository = MemoryTeacherAssignmentRepository()
    assignments = TeacherAssignmentService(
        repository=assignment_repository,
        roster_provider=FakeRosterAssignmentProvider(
            RosterAssignmentBatch(supported=False)
        ),
        now=Clock(),
    )
    app = FastAPI()
    app.state.permission_service = permissions
    app.state.teacher_assignment_service = assignments
    app.dependency_overrides[authenticated_principal] = lambda: principal
    app.dependency_overrides[get_permission_service] = lambda: permissions
    app.include_router(router)
    return TestClient(app), actor, assignment_repository


def test_roster_admin_can_create_assignment() -> None:
    client, _, _ = client_for(scopes=frozenset({PermissionScope.ROSTER}))
    teacher_id = uuid4()
    class_id = uuid4()

    response = client.post(
        "/api/v1/teacher-class-assignments",
        json={
            "teacher_id": str(teacher_id),
            "class_id": str(class_id),
            "role": "primary",
        },
    )

    assert response.status_code == 201
    assert response.json()["teacher_id"] == str(teacher_id)
    assert response.json()["role"] == "primary"


def test_assignment_creation_requires_roster_scope() -> None:
    client, _, _ = client_for(scopes=frozenset({PermissionScope.BILLING}))

    response = client.post(
        "/api/v1/teacher-class-assignments",
        json={
            "teacher_id": str(uuid4()),
            "class_id": str(uuid4()),
            "role": "co_teacher",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "permission_denied"


def test_teacher_can_query_own_classes_from_implicit_scope() -> None:
    client, actor, repository = client_for(
        role="teacher",
        scopes=frozenset(),
    )
    class_id = uuid4()
    repository.class_names[class_id] = ("JSS 3", "JSS3")
    assert actor.school_id is not None
    assignment = TeacherClassAssignment(
        id=uuid4(),
        school_id=actor.school_id,
        teacher_id=actor.user_id,
        class_id=class_id,
        role=TeacherAssignmentRole.PRIMARY,
        source=TeacherAssignmentSource.MANUAL,
        assigned_at=Clock()(),
    )
    repository.assignments[assignment.id] = assignment

    response = client.get("/api/v1/teachers/me/classes")

    assert response.status_code == 200
    assert response.json()[0]["class_name"] == "JSS 3"


def test_roster_sync_returns_explicit_fallback() -> None:
    client, _, _ = client_for(scopes=frozenset({PermissionScope.IT_SSO}))

    response = client.post("/api/v1/teacher-class-assignments/roster-sync")

    assert response.status_code == 200
    assert response.json()["status"] == "manual_fallback_required"
    assert "Assign teachers manually" in response.json()["message"]


def test_remove_unknown_assignment_returns_404() -> None:
    client, _, _ = client_for(scopes=frozenset({PermissionScope.ROSTER}))

    response = client.delete(
        f"/api/v1/teacher-class-assignments/{uuid4()}"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "assignment_not_found"


def test_invalid_assignment_role_is_rejected() -> None:
    client, _, _ = client_for(scopes=frozenset({PermissionScope.ROSTER}))

    response = client.post(
        "/api/v1/teacher-class-assignments",
        json={
            "teacher_id": str(uuid4()),
            "class_id": str(uuid4()),
            "role": "assistant",
        },
    )

    assert response.status_code == 422
