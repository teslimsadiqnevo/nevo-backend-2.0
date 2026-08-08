import pytest

from nevo.domain.partner_inquiries.vocabulary import (
    PartnerInquiryContactMethod,
    PartnerInquiryRole,
)
from nevo.partner_inquiries.errors import InvalidPartnerContactError
from nevo.partner_inquiries.service import PartnerInquiryService

from .fakes import MemoryPartnerInquiryRepository


def service() -> tuple[PartnerInquiryService, MemoryPartnerInquiryRepository]:
    repository = MemoryPartnerInquiryRepository()
    return PartnerInquiryService(repository=repository), repository


@pytest.mark.asyncio
async def test_submit_normalizes_name_and_email_contact() -> None:
    instance, repository = service()

    view = await instance.submit(
        full_name="  Ada   Lovelace ",
        school_name="  Bright Future  Academy ",
        role=PartnerInquiryRole.HEAD_TEACHER,
        contact=" Ada.Lovelace@School.EDU ",
        message="  Curious about adaptive lessons.  ",
    )

    assert view.full_name == "Ada Lovelace"
    assert view.school_name == "Bright Future Academy"
    assert view.contact == "ada.lovelace@school.edu"
    assert view.contact_method is PartnerInquiryContactMethod.EMAIL
    assert view.message == "Curious about adaptive lessons."
    assert repository.created[0].role is PartnerInquiryRole.HEAD_TEACHER


@pytest.mark.asyncio
async def test_submit_classifies_phone_contact() -> None:
    instance, _ = service()

    view = await instance.submit(
        full_name="Grace Hopper",
        school_name="Naval Academy",
        role=PartnerInquiryRole.SCHOOL_OWNER,
        contact="+234 (0) 803-555-0199",
        message=None,
    )

    assert view.contact_method is PartnerInquiryContactMethod.PHONE
    assert view.contact == "+23408035550199"
    assert view.message is None


@pytest.mark.asyncio
async def test_submit_blank_message_is_stored_as_none() -> None:
    instance, _ = service()

    view = await instance.submit(
        full_name="Grace Hopper",
        school_name="Naval Academy",
        role=PartnerInquiryRole.OTHER,
        contact="grace@navy.mil",
        message="   ",
    )

    assert view.message is None


@pytest.mark.asyncio
async def test_submit_rejects_unrecognizable_contact() -> None:
    instance, _ = service()

    with pytest.raises(InvalidPartnerContactError):
        await instance.submit(
            full_name="Grace Hopper",
            school_name="Naval Academy",
            role=PartnerInquiryRole.OTHER,
            contact="not-a-contact",
            message=None,
        )
