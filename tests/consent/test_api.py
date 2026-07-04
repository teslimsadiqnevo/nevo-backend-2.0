from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nevo.api.auth import authenticated_principal
from nevo.api.consent import router
from nevo.auth.entities import AuthPrincipal
from nevo.consent.entities import ConsentRecordView
from nevo.consent.service import ConsentService
from nevo.domain.accounts.vocabulary import (
    ConsentStatus,
    ConsentType,
)
from nevo.domain.permissions.vocabulary import PermissionScope
from nevo.permissions.entities import PermissionSnapshot
from nevo.permissions.service import PermissionService
from tests.permissions.fakes import (
    DeterministicInvitationTokens,
    FakePasswordHasher,
    MemoryPermissionRepository,
)

from .fakes import FixedConsentTokenService, MemoryConsentRepository

NOW = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)


def client_for(
    *,
    role: str,
    scopes: frozenset[PermissionScope],
) -> tuple[TestClient, PermissionSnapshot, MemoryConsentRepository]:
    snapshot = PermissionSnapshot(
        user_id=uuid4(),
        school_id=uuid4(),
        role=role,
        status="active",
        school_auth_method="email_password",
        assigned_scopes=scopes,
    )
    principal = AuthPrincipal(
        user_id=snapshot.user_id,
        role=role,
        session_id=uuid4(),
    )
    permissions = PermissionService(
        repository=MemoryPermissionRepository([snapshot]),
        invitation_tokens=DeterministicInvitationTokens(),
        password_hasher=FakePasswordHasher(),
        now=lambda: NOW,
    )
    repository = MemoryConsentRepository()
    consent_service = ConsentService(
        repository=repository,
        token_service=FixedConsentTokenService(),
        public_base_url="https://app.nevo.test",
        now=lambda: NOW,
    )
    app = FastAPI()
    app.state.permission_service = permissions
    app.state.consent_service = consent_service
    app.dependency_overrides[authenticated_principal] = lambda: principal
    app.include_router(router)
    return TestClient(app), snapshot, repository


def test_senco_can_confirm_school_collected_consent() -> None:
    client, _, _ = client_for(
        role="senco_admin",
        scopes=frozenset(),
    )
    student_id = uuid4()

    response = client.post(
        "/api/v1/consents/school-confirmations",
        json={
            "student_id": str(student_id),
            "consent_types": ["data_processing"],
            "confirmed_via": "written",
        },
    )

    assert response.status_code == 200
    assert response.json()[0]["student_id"] == str(student_id)
    assert response.json()[0]["confirmation_source"] == "school"


def test_non_senco_cannot_manage_consent() -> None:
    client, _, _ = client_for(
        role="other_admin",
        scopes=frozenset({PermissionScope.BILLING}),
    )

    response = client.post(
        "/api/v1/consents/school-confirmations",
        json={
            "student_id": str(uuid4()),
            "consent_types": ["data_processing"],
            "confirmed_via": "written",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "permission_denied"


def test_parent_request_is_queued_without_exposing_token() -> None:
    client, _, _ = client_for(
        role="senco_admin",
        scopes=frozenset(),
    )

    response = client.post(
        f"/api/v1/students/{uuid4()}/parent-consent-requests",
        json={
            "parent_name": "Ada Parent",
            "parent_contact": "ada@example.com",
            "contact_method": "email",
            "consent_types": ["data_processing"],
        },
    )

    assert response.status_code == 202
    assert response.json()["delivery_status"] == "queued"
    assert "token" not in response.json()
    assert "consent_url" not in response.json()


def test_public_parent_completion_consumes_invitation() -> None:
    client, _, _ = client_for(
        role="senco_admin",
        scopes=frozenset(),
    )
    student_id = uuid4()
    client.post(
        f"/api/v1/students/{student_id}/parent-consent-requests",
        json={
            "parent_name": "Ada Parent",
            "parent_contact": "ada@example.com",
            "contact_method": "email",
        },
    )

    first = client.post(
        "/api/v1/consents/parent/complete",
        json={"token": FixedConsentTokenService.token},
    )
    second = client.post(
        "/api/v1/consents/parent/complete",
        json={"token": FixedConsentTokenService.token},
    )

    assert first.status_code == 200
    assert first.json()["student_id"] == str(student_id)
    assert second.status_code == 400
    assert second.json()["detail"]["code"] == "invalid_consent_invitation"


def test_student_gate_reports_pending_and_confirmed() -> None:
    client, snapshot, repository = client_for(
        role="student",
        scopes=frozenset(),
    )

    pending = client.get("/api/v1/students/me/consent-gate")
    repository.records[
        (snapshot.user_id, ConsentType.DATA_PROCESSING)
    ] = ConsentRecordView(
        id=uuid4(),
        student_id=snapshot.user_id,
        consent_type=ConsentType.DATA_PROCESSING,
        status=ConsentStatus.CONFIRMED,
        confirmation_source=None,
        confirmed_via=None,
        confirmed_at=NOW,
    )
    confirmed = client.get("/api/v1/students/me/consent-gate")

    assert pending.status_code == 200
    assert not pending.json()["granted"]
    assert confirmed.status_code == 200
    assert confirmed.json()["granted"]
