import logging
import re

from nevo.domain.partner_inquiries.vocabulary import (
    PartnerInquiryContactMethod,
    PartnerInquiryIntent,
    PartnerInquiryRole,
    PartnerInquirySource,
)
from nevo.partner_inquiries.entities import (
    PartnerInquiryDraft,
    PartnerInquiryView,
)
from nevo.partner_inquiries.errors import InvalidPartnerContactError, MissingContactError
from nevo.partner_inquiries.notifier import LeadEmailNotifier
from nevo.partner_inquiries.ports import PartnerInquiryRepository

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_PATTERN = re.compile(r"^\+?[1-9]\d{6,14}$")


logger = logging.getLogger(__name__)


class PartnerInquiryService:
    def __init__(
        self,
        *,
        repository: PartnerInquiryRepository,
        notifier: "LeadEmailNotifier | None" = None,
    ) -> None:
        self._repository = repository
        self._notifier = notifier

    async def submit(
        self,
        *,
        full_name: str,
        school_name: str,
        role: PartnerInquiryRole,
        contact: str | None = None,
        message: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        student_count: int | None = None,
        intent: PartnerInquiryIntent | None = None,
        source: PartnerInquirySource = PartnerInquirySource.WEBSITE,
    ) -> PartnerInquiryView:
        """Record a school's interest.

        The website form sends one `contact`; the event form sends email and
        phone separately. Either way `contact`/`contact_method` stay populated,
        so anything already reading a lead keeps working.
        """
        primary = contact or email or phone
        if not primary:
            raise MissingContactError
        normalized_contact, contact_method = self._classify_contact(primary)
        draft = PartnerInquiryDraft(
            full_name=" ".join(full_name.split()),
            school_name=" ".join(school_name.split()),
            role=role,
            contact=normalized_contact,
            contact_method=contact_method,
            message=self._normalize_message(message),
            email=(email or "").strip().casefold() or None,
            phone=(phone or "").strip() or None,
            student_count=student_count,
            intent=intent,
            source=source,
        )
        view = await self._repository.create(draft)
        # The lead is committed by this point. Alerting is best effort and is
        # guarded here rather than only inside the notifier, because this is
        # the boundary that faces the school: someone standing at the stand
        # must see a confirmation, not an error, when our mail provider is
        # having a bad afternoon. The export is the system of record.
        if self._notifier is not None:
            try:
                await self._notifier.notify(view)
            except Exception:
                logger.warning(
                    "Lead alert failed for inquiry %s; the lead is saved",
                    view.id,
                    exc_info=True,
                )
        return view

    async def recent(
        self,
        *,
        source: PartnerInquirySource | None = None,
        limit: int = 500,
    ) -> list[PartnerInquiryView]:
        return await self._repository.recent(source=source, limit=limit)

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
