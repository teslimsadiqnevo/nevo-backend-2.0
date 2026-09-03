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


# --- the exact payload the TOSSE page sends -------------------------------
# Captured off the wire from a real submission (SCRUM-117), not transcribed
# from the spec. Every field here is load-bearing: the enum values were
# guessed before the ticket was settled and two of the three intent cards
# would have been rejected at the stand.

WIRE_PAYLOAD = {
    "name": "Adebola Okafor",
    "role": "Academic Director / Head of School",
    "school_name": "Greenfield Academy",
    "student_count": 280,
    "phone": "+234 803 456 7890",
    "email": "adebola@greenfieldacademy.ng",
    "intent": "founding_partner",
}


def test_the_page_payload_validates_exactly_as_sent() -> None:
    from nevo.api.partner_inquiries import TosseInterestRequest

    parsed = TosseInterestRequest(**WIRE_PAYLOAD)

    assert parsed.full_name == "Adebola Okafor"
    assert parsed.school_name == "Greenfield Academy"
    assert parsed.student_count == 280
    # A phone with spaces is what a person types; it must not be rejected.
    assert parsed.phone == "+234 803 456 7890"


def test_every_intent_card_on_the_page_is_accepted() -> None:
    """Two of these three used to 422, so two thirds of leads were lost."""
    from nevo.api.partner_inquiries import TosseInterestRequest

    for intent in ("founding_partner", "schedule_walkthrough", "contact_me"):
        parsed = TosseInterestRequest(**{**WIRE_PAYLOAD, "intent": intent})
        assert parsed.intent.value == intent


def test_every_role_the_dropdown_offers_maps_to_a_distinct_value() -> None:
    from nevo.domain.partner_inquiries.vocabulary import parse_role

    labels = [
        "School Proprietor / Owner",
        "Academic Director / Head of School",
        "Teacher",
        "Parent",
        "Other",
    ]
    roles = [parse_role(label) for label in labels]

    assert None not in roles
    assert len(set(roles)) == len(labels), "two labels collapsed to one role"


def test_an_unfamiliar_role_is_recorded_rather_than_rejected() -> None:
    """A lead at a stand is worth more than a tidy enum."""
    from nevo.api.partner_inquiries import TosseInterestRequest
    from nevo.domain.partner_inquiries.vocabulary import PartnerInquiryRole, parse_role

    parsed = TosseInterestRequest(**{**WIRE_PAYLOAD, "role": "Bursar"})

    assert parse_role(parsed.role) is None
    assert (parse_role(parsed.role) or PartnerInquiryRole.OTHER) is PartnerInquiryRole.OTHER


def test_the_response_carries_the_status_the_page_reads() -> None:
    """The page shows its retry notice unless this field is present."""
    from uuid import uuid4

    from nevo.api.partner_inquiries import TosseInterestResponse

    body = TosseInterestResponse(id=uuid4()).model_dump(by_alias=True)

    assert body["status"] == "received"
    assert "id" in body
