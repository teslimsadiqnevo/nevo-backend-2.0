from fastapi import FastAPI
from fastapi.testclient import TestClient

from nevo.api.partner_inquiries import router
from nevo.partner_inquiries.service import PartnerInquiryService

from .fakes import MemoryPartnerInquiryRepository


def client_for() -> tuple[TestClient, MemoryPartnerInquiryRepository]:
    repository = MemoryPartnerInquiryRepository()
    app = FastAPI()
    app.state.partner_inquiry_service = PartnerInquiryService(
        repository=repository,
    )
    app.include_router(router)
    return TestClient(app), repository


def test_submit_partner_inquiry_stores_and_returns_record() -> None:
    client, repository = client_for()

    response = client.post(
        "/api/v1/partner-inquiries",
        json={
            "full_name": "Ada Lovelace",
            "school_name": "Bright Future Academy",
            "role": "head_teacher",
            "contact": "ada@brightfuture.example",
            "message": "Curious about adaptive lessons.",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["full_name"] == "Ada Lovelace"
    assert body["role"] == "head_teacher"
    assert body["contact_method"] == "email"
    assert len(repository.created) == 1


def test_submit_partner_inquiry_allows_optional_message() -> None:
    client, _ = client_for()

    response = client.post(
        "/api/v1/partner-inquiries",
        json={
            "full_name": "Grace Hopper",
            "school_name": "Naval Academy",
            "role": "school_owner",
            "contact": "+2348035550199",
        },
    )

    assert response.status_code == 201
    assert response.json()["message"] is None
    assert response.json()["contact_method"] == "phone"


def test_submit_partner_inquiry_rejects_invalid_contact() -> None:
    client, _ = client_for()

    response = client.post(
        "/api/v1/partner-inquiries",
        json={
            "full_name": "Grace Hopper",
            "school_name": "Naval Academy",
            "role": "other",
            "contact": "not-a-contact",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_partner_contact"


def test_submit_partner_inquiry_rejects_missing_role() -> None:
    client, _ = client_for()

    response = client.post(
        "/api/v1/partner-inquiries",
        json={
            "full_name": "Grace Hopper",
            "school_name": "Naval Academy",
            "contact": "grace@navy.mil",
        },
    )

    assert response.status_code == 422


def test_submit_partner_inquiry_rejects_unknown_role() -> None:
    client, _ = client_for()

    response = client.post(
        "/api/v1/partner-inquiries",
        json={
            "full_name": "Grace Hopper",
            "school_name": "Naval Academy",
            "role": "principal",
            "contact": "grace@navy.mil",
        },
    )

    assert response.status_code == 422


def test_service_unavailable_when_not_wired() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.post(
        "/api/v1/partner-inquiries",
        json={
            "full_name": "Grace Hopper",
            "school_name": "Naval Academy",
            "role": "other",
            "contact": "grace@navy.mil",
        },
    )

    assert response.status_code == 503
