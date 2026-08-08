import re

from nevo.domain.partner_inquiries.vocabulary import (
    PartnerInquiryContactMethod,
    PartnerInquiryRole,
)
from nevo.partner_inquiries.entities import (
    PartnerInquiryDraft,
    PartnerInquiryView,
)
from nevo.partner_inquiries.errors import InvalidPartnerContactError
from nevo.partner_inquiries.ports import PartnerInquiryRepository

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_PATTERN = re.compile(r"^\+?[1-9]\d{6,14}$")


class PartnerInquiryService:
    def __init__(self, *, repository: PartnerInquiryRepository) -> None:
        self._repository = repository

    async def submit(
        self,
        *,
        full_name: str,
        school_name: str,
        role: PartnerInquiryRole,
        contact: str,
        message: str | None,
    ) -> PartnerInquiryView:
        normalized_contact, contact_method = self._classify_contact(contact)
        draft = PartnerInquiryDraft(
            full_name=" ".join(full_name.split()),
            school_name=" ".join(school_name.split()),
            role=role,
            contact=normalized_contact,
            contact_method=contact_method,
            message=self._normalize_message(message),
        )
        return await self._repository.create(draft)

    @staticmethod
    def _normalize_message(message: str | None) -> str | None:
        if message is None:
            return None
        normalized = message.strip()
        return normalized or None

    @staticmethod
    def _classify_contact(
        contact: str,
    ) -> tuple[str, PartnerInquiryContactMethod]:
        normalized = contact.strip()
        if EMAIL_PATTERN.fullmatch(normalized):
            return normalized.casefold(), PartnerInquiryContactMethod.EMAIL

        digits_only = re.sub(r"[\s()-]", "", normalized)
        if digits_only.startswith("00"):
            digits_only = f"+{digits_only[2:]}"
        if PHONE_PATTERN.fullmatch(digits_only):
            return digits_only, PartnerInquiryContactMethod.PHONE

        raise InvalidPartnerContactError
