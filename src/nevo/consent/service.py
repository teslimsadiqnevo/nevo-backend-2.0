import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from nevo.auth.entities import AuthPrincipal
from nevo.consent.entities import (
    ConsentActor,
    ConsentGate,
    ConsentRecordView,
    ParentConsentCompletion,
    ParentConsentRequestDraft,
    ParentLinkView,
    QueuedParentConsentRequest,
)
from nevo.consent.errors import (
    ConsentRequiredError,
    InvalidConsentMethodError,
    InvalidParentContactError,
    StudentConsentAccessError,
)
from nevo.consent.ports import ConsentRepository, ConsentTokenService
from nevo.domain.accounts.vocabulary import (
    ConsentMethod,
    ConsentStatus,
    ConsentType,
)
from nevo.domain.consent.vocabulary import ParentContactMethod

PARENT_CONSENT_LIFETIME = timedelta(days=7)
REQUIRED_LEARNING_CONSENT = ConsentType.DATA_PROCESSING
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")


class ConsentService:
    def __init__(
        self,
        *,
        repository: ConsentRepository,
        token_service: ConsentTokenService,
        public_base_url: str,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._token_service = token_service
        self._public_base_url = public_base_url.rstrip("/")
        self._now = now or (lambda: datetime.now(UTC))

    async def confirm_by_school(
        self,
        actor: ConsentActor,
        *,
        student_id: UUID,
        consent_types: frozenset[ConsentType],
        confirmed_via: ConsentMethod,
    ) -> list[ConsentRecordView]:
        if confirmed_via is ConsentMethod.DIGITAL:
            raise InvalidConsentMethodError
        return await self._repository.confirm_by_school(
            school_id=actor.school_id,
            student_id=student_id,
            consent_types=self._required_types(consent_types),
            confirmed_by_user_id=actor.user_id,
            confirmed_via=confirmed_via,
            confirmed_at=self._now(),
        )

    async def request_parent_consent(
        self,
        actor: ConsentActor,
        *,
        student_id: UUID,
        parent_name: str,
        parent_contact: str,
        contact_method: ParentContactMethod,
        consent_types: frozenset[ConsentType],
    ) -> QueuedParentConsentRequest:
        normalized_name = " ".join(parent_name.split())
        normalized_contact = self._normalize_contact(
            parent_contact,
            contact_method,
        )
        token, token_digest = self._token_service.issue()
        now = self._now()
        invitation_id = uuid4()
        parent_link_id = uuid4()
        draft = ParentConsentRequestDraft(
            invitation_id=invitation_id,
            parent_link_id=parent_link_id,
            school_id=actor.school_id,
            student_id=student_id,
            parent_name=normalized_name,
            parent_contact=normalized_contact,
            contact_method=contact_method,
            consent_types=self._required_types(consent_types),
            token_digest=token_digest,
            consent_url=(
                f"{self._public_base_url}/consent/parent?token={token}"
            ),
            requested_by_user_id=actor.user_id,
            created_at=now,
            expires_at=now + PARENT_CONSENT_LIFETIME,
        )
        return await self._repository.create_parent_request(draft)

    async def complete_parent_consent(
        self,
        *,
        token: str,
    ) -> ParentConsentCompletion | None:
        return await self._repository.complete_parent_request(
            token_digest=self._token_service.digest(token),
            completed_at=self._now(),
        )

    async def parent_links(
        self,
        actor: ConsentActor,
        *,
        student_id: UUID,
    ) -> list[ParentLinkView]:
        return await self._repository.parent_links(
            school_id=actor.school_id,
            student_id=student_id,
        )

    async def student_gate(
        self,
        principal: AuthPrincipal,
    ) -> ConsentGate:
        if principal.role != "student":
            raise StudentConsentAccessError
        granted = await self._repository.has_confirmed_consent(
            student_id=principal.user_id,
            consent_type=REQUIRED_LEARNING_CONSENT,
        )
        return ConsentGate(
            student_id=principal.user_id,
            granted=granted,
            required_type=REQUIRED_LEARNING_CONSENT,
            status=(
                ConsentStatus.CONFIRMED
                if granted
                else ConsentStatus.PENDING
            ),
        )

    async def require_student_consent(
        self,
        principal: AuthPrincipal,
    ) -> ConsentGate:
        gate = await self.student_gate(principal)
        if not gate.granted:
            raise ConsentRequiredError
        return gate

    async def initialize_roster_student(self, student_id: UUID) -> None:
        await self._repository.ensure_pending(
            student_id=student_id,
            consent_types=frozenset({REQUIRED_LEARNING_CONSENT}),
        )

    @staticmethod
    def _required_types(
        consent_types: frozenset[ConsentType],
    ) -> frozenset[ConsentType]:
        return consent_types or frozenset({REQUIRED_LEARNING_CONSENT})

    @staticmethod
    def _normalize_contact(
        contact: str,
        method: ParentContactMethod,
    ) -> str:
        normalized = contact.strip()
        if method is ParentContactMethod.EMAIL:
            normalized = normalized.casefold()
            if not EMAIL_PATTERN.fullmatch(normalized):
                raise InvalidParentContactError
            return normalized

        normalized = re.sub(r"[\s()-]", "", normalized)
        if normalized.startswith("00"):
            normalized = f"+{normalized[2:]}"
        if not PHONE_PATTERN.fullmatch(normalized):
            raise InvalidParentContactError
        return normalized
