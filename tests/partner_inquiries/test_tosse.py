"""TOSSE lead capture.

This runs once, at a stand, on event wifi, in front of the schools we are
trying to sign. The rules that matter are: a lead is never lost, and a
notification failure is not a lead failure.
"""
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from nevo.domain.partner_inquiries.vocabulary import (
    PartnerInquiryContactMethod,
    PartnerInquiryIntent,
    PartnerInquiryRole,
    PartnerInquirySource,
)
from nevo.partner_inquiries.entities import PartnerInquiryView
from nevo.partner_inquiries.errors import MissingContactError
from nevo.partner_inquiries.notifier import LeadAlertSettings, LeadEmailNotifier
from nevo.partner_inquiries.service import PartnerInquiryService


class FakeRepository:
    def __init__(self) -> None:
        self.created: list[object] = []

    async def create(self, draft):  # type: ignore[no-untyped-def]
        self.created.append(draft)
        return PartnerInquiryView(
            id=uuid4(),
            full_name=draft.full_name,
            school_name=draft.school_name,
            role=draft.role,
            contact=draft.contact,
            contact_method=draft.contact_method,
            message=draft.message,
            created_at=datetime(2026, 9, 3, 10, 30, tzinfo=UTC),
            email=draft.email,
            phone=draft.phone,
            student_count=draft.student_count,
            intent=draft.intent,
            source=draft.source,
        )

    async def recent(self, *, source=None, limit=500):  # type: ignore[no-untyped-def]
        return []


class ExplodingNotifier:
    async def notify(self, view):  # type: ignore[no-untyped-def]
        raise RuntimeError("mail provider down")


class RecordingNotifier:
    def __init__(self) -> None:
        self.seen: list[PartnerInquiryView] = []

    async def notify(self, view):  # type: ignore[no-untyped-def]
        self.seen.append(view)


async def submit(service: PartnerInquiryService, **overrides):  # type: ignore[no-untyped-def]
    payload = {
        "full_name": "  Adaeze   Nwosu ",
        "school_name": "Bright Star Academy",
        "role": PartnerInquiryRole.PROPRIETOR,
        "email": "Adaeze@BrightStar.NG",
        "phone": "+2348012345678",
        "student_count": 420,
        "intent": PartnerInquiryIntent.FOUNDING_PARTNER,
        "source": PartnerInquirySource.TOSSE_2026,
    }
    payload.update(overrides)
    return await service.submit(**payload)


async def test_an_event_lead_is_stored_with_everything_the_form_collected() -> None:
    repository = FakeRepository()
    view = await submit(PartnerInquiryService(repository=repository))

    assert view.school_name == "Bright Star Academy"
    assert view.student_count == 420
    assert view.intent is PartnerInquiryIntent.FOUNDING_PARTNER
    assert view.source is PartnerInquirySource.TOSSE_2026
    assert view.phone == "+2348012345678"


async def test_names_are_tidied_and_emails_lowercased() -> None:
    view = await submit(PartnerInquiryService(repository=FakeRepository()))

    assert view.full_name == "Adaeze Nwosu"
    assert view.email == "adaeze@brightstar.ng"


async def test_the_legacy_contact_fields_stay_populated() -> None:
    """Anything already reading a lead keeps working."""
    view = await submit(PartnerInquiryService(repository=FakeRepository()))

    assert view.contact == "adaeze@brightstar.ng"
    assert view.contact_method is PartnerInquiryContactMethod.EMAIL


async def test_a_failed_alert_never_loses_the_lead() -> None:
    """The school is standing at the stand. Saving is what matters."""
    repository = FakeRepository()
    service = PartnerInquiryService(repository=repository, notifier=ExplodingNotifier())

    view = await submit(service)

    assert view.school_name == "Bright Star Academy"
    assert len(repository.created) == 1


async def test_every_submission_raises_an_alert() -> None:
    notifier = RecordingNotifier()
    service = PartnerInquiryService(repository=FakeRepository(), notifier=notifier)

    await submit(service)

    assert len(notifier.seen) == 1
    assert notifier.seen[0].school_name == "Bright Star Academy"


async def test_a_lead_with_no_way_to_reach_them_is_refused() -> None:
    service = PartnerInquiryService(repository=FakeRepository())

    with pytest.raises(MissingContactError):
        await submit(service, email=None, phone=None, contact=None)


async def test_a_phone_only_lead_is_accepted() -> None:
    """Not everyone at a stand will give an email."""
    view = await submit(PartnerInquiryService(repository=FakeRepository()), email=None)

    assert view.phone == "+2348012345678"
    assert view.contact_method is PartnerInquiryContactMethod.PHONE


async def test_the_website_form_still_works_unchanged() -> None:
    """No new field is required, and it stays tagged as a website lead."""
    view = await PartnerInquiryService(repository=FakeRepository()).submit(
        full_name="Chidi Okeke",
        school_name="Old Site School",
        role=PartnerInquiryRole.HEAD_TEACHER,
        contact="chidi@example.com",
        message="Please get in touch.",
    )

    assert view.source is PartnerInquirySource.WEBSITE
    assert view.intent is None
    assert view.student_count is None


# --- the alert itself ------------------------------------------------------


def a_view(**overrides) -> PartnerInquiryView:  # type: ignore[no-untyped-def]
    base = {
        "id": uuid4(),
        "full_name": "Adaeze Nwosu",
        "school_name": "Bright Star Academy",
        "role": PartnerInquiryRole.PROPRIETOR,
        "contact": "adaeze@brightstar.ng",
        "contact_method": PartnerInquiryContactMethod.EMAIL,
        "message": None,
        "created_at": datetime(2026, 9, 3, 10, 30, tzinfo=UTC),
        "email": "adaeze@brightstar.ng",
        "phone": "+2348012345678",
        "student_count": 420,
        "intent": PartnerInquiryIntent.FOUNDING_PARTNER,
        "source": PartnerInquirySource.TOSSE_2026,
    }
    base.update(overrides)
    return PartnerInquiryView(**base)  # type: ignore[arg-type]


def test_the_alert_is_readable_on_a_phone_at_a_stand() -> None:
    summary = LeadEmailNotifier.summary(a_view())

    assert "Bright Star Academy" in summary
    assert "420" in summary
    assert "founding partner" in summary
    assert "+2348012345678" in summary
    # No internal identifiers in something a person reads between conversations.
    assert "tosse_2026" in summary
    assert "PartnerInquiryRole" not in summary


def test_the_alert_omits_what_was_not_collected() -> None:
    summary = LeadEmailNotifier.summary(a_view(student_count=None, phone=None, intent=None))

    assert "Students:" not in summary
    assert "Phone:" not in summary
    assert "Wants:" not in summary


def test_no_recipients_means_no_alerts_but_still_no_crash() -> None:
    notifier = LeadEmailNotifier(
        delivery=None,  # type: ignore[arg-type]
        settings=LeadAlertSettings(LEAD_ALERT_RECIPIENTS=""),  # type: ignore[call-arg]
    )

    assert not notifier.configured


def test_recipients_are_parsed_from_a_comma_separated_list() -> None:
    settings = LeadAlertSettings(  # type: ignore[call-arg]
        LEAD_ALERT_RECIPIENTS=" bolu@nevolearning.com , teslim@nevolearning.com "
    )

    assert settings.addresses == ["bolu@nevolearning.com", "teslim@nevolearning.com"]
