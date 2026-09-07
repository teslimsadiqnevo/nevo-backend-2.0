"""The parent-facing consent screen: what it may read, and what it may record."""
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nevo.api.consent import router as consent_router
from nevo.api.product_auth import router as product_auth_router
from nevo.consent.entities import ConsentActor, ConsentRecordView
from nevo.consent.service import ConsentService
from nevo.domain.accounts.vocabulary import ConsentStatus, ConsentType
from nevo.domain.consent.vocabulary import ParentContactMethod, ParentRightType

from .fakes import FixedConsentTokenService, MemoryConsentRepository

NOW = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)
TOKEN = FixedConsentTokenService.token


async def _invite(
    service: ConsentService,
    repository: MemoryConsentRepository,
    *,
    student_first_name: str = "Amara",
    school_name: str = "Bright Star Academy",
) -> tuple[ConsentActor, object]:
    actor = ConsentActor(user_id=uuid4(), school_id=uuid4())
    student_id = uuid4()
    repository.student_first_names[student_id] = student_first_name
    repository.school_names[actor.school_id] = school_name
    repository.school_phone = "+2348012345678"
    repository.school_email = "office@brightstar.test"
    queued = await service.request_parent_consent(
        actor,
        student_id=student_id,
        parent_name="Ngozi Okafor",
        parent_contact="parent@example.test",
        contact_method=ParentContactMethod.EMAIL,
        consent_types=frozenset({ConsentType.DATA_PROCESSING}),
    )
    return actor, queued


def build() -> tuple[TestClient, ConsentService, MemoryConsentRepository]:
    repository = MemoryConsentRepository()
    service = ConsentService(
        repository=repository,
        token_service=FixedConsentTokenService(),
        public_base_url="https://app.nevo.test",
        now=lambda: NOW,
    )
    app = FastAPI()
    app.state.consent_service = service
    app.include_router(consent_router)
    app.include_router(product_auth_router)
    return TestClient(app), service, repository


def test_parent_token_names_the_child_and_the_school() -> None:
    client, service, repository = build()
    import anyio

    anyio.run(_invite, service, repository)

    response = client.get(f"/api/v1/consents/parent/{TOKEN}")

    assert response.status_code == 200
    body = response.json()
    # Rendered generically this screen would not be informed consent, so these
    # are the fields the page exists to show.
    assert body["studentFirstName"] == "Amara"
    assert body["schoolName"] == "Bright Star Academy"
    assert body["schoolPhone"] == "+2348012345678"
    assert body["schoolEmail"] == "office@brightstar.test"
    assert body["consentTypes"] == ["data_processing"]
    assert body["status"] == "pending"


def test_unknown_parent_token_is_not_found() -> None:
    client, _, _ = build()

    response = client.get("/api/v1/consents/parent/not-a-real-token")

    assert response.status_code == 404


def test_parent_arriving_after_withdrawal_sees_the_withdrawn_state() -> None:
    client, service, repository = build()
    import anyio

    anyio.run(_invite, service, repository)
    client.post(
        f"/api/v1/parent/{TOKEN}/rights",
        json={"requestType": "withdraw_consent"},
    )

    response = client.get(f"/api/v1/consents/parent/{TOKEN}")

    assert response.status_code == 200
    assert response.json()["status"] == "withdrawn"


def test_objection_reason_is_recorded_not_discarded() -> None:
    client, service, repository = build()
    import anyio

    anyio.run(_invite, service, repository)

    response = client.post(
        f"/api/v1/parent/{TOKEN}/rights",
        json={
            "requestType": "object",
            "reason": "I was not told the lesson recordings are kept.",
        },
    )

    assert response.status_code == 202
    assert response.json()["reasonRecorded"] is True
    assert repository.rights == [
        (
            repository.rights[0][0],
            ParentRightType.OBJECT,
            "I was not told the lesson recordings are kept.",
        )
    ]


def test_rights_endpoint_resolves_the_consent_service_token() -> None:
    """It hashed the token itself before, so no live link ever matched."""
    client, service, repository = build()
    import anyio

    anyio.run(_invite, service, repository)

    response = client.post(
        f"/api/v1/parent/{TOKEN}/rights",
        json={"requestType": "request_data"},
    )

    assert response.status_code == 202
    assert response.json()["requestType"] == "request_data"


def test_student_gate_distinguishes_withdrawn_from_pending() -> None:
    repository = MemoryConsentRepository()
    service = ConsentService(
        repository=repository,
        token_service=FixedConsentTokenService(),
        public_base_url="https://app.nevo.test",
        now=lambda: NOW,
    )
    student_id = uuid4()
    repository.records[(student_id, ConsentType.DATA_PROCESSING)] = ConsentRecordView(
        id=uuid4(),
        student_id=student_id,
        consent_type=ConsentType.DATA_PROCESSING,
        status=ConsentStatus.WITHDRAWN,
        confirmation_source=None,
        confirmed_via=None,
        confirmed_at=None,
    )

    import anyio

    from nevo.auth.entities import AuthPrincipal

    gate = anyio.run(
        lambda: service.student_gate(
            AuthPrincipal(user_id=student_id, role="student", session_id=uuid4())
        )
    )

    assert gate.granted is False
    assert gate.status is ConsentStatus.WITHDRAWN


def test_a_right_exercised_before_completion_creates_the_parent_account() -> None:
    """parent_id and account_created move together, as the table requires."""
    client, service, repository = build()
    import anyio

    anyio.run(_invite, service, repository)
    link = next(iter(repository.links.values()))
    assert link.parent_id is None

    client.post(
        f"/api/v1/parent/{TOKEN}/rights",
        json={"requestType": "request_data"},
    )

    updated = next(iter(repository.links.values()))
    assert updated.parent_id is not None
    assert updated.account_created is True
