from dataclasses import replace
from datetime import datetime
from uuid import UUID, uuid4

from nevo.consent.entities import (
    ConsentRecordView,
    ParentConsentCompletion,
    ParentConsentRequestDraft,
    ParentLinkView,
    QueuedParentConsentRequest,
)
from nevo.domain.accounts.vocabulary import (
    ConsentMethod,
    ConsentStatus,
    ConsentType,
)
from nevo.domain.consent.vocabulary import (
    ConsentConfirmationSource,
    ConsentDeliveryStatus,
)


class MemoryConsentRepository:
    def __init__(self) -> None:
        self.records: dict[tuple[UUID, ConsentType], ConsentRecordView] = {}
        self.links: dict[UUID, ParentLinkView] = {}
        self.requests: dict[str, ParentConsentRequestDraft] = {}
        self.completed_tokens: set[str] = set()
        self.pending_initializations: list[
            tuple[UUID, frozenset[ConsentType]]
        ] = []

    async def confirm_by_school(
        self,
        *,
        school_id: UUID,
        student_id: UUID,
        consent_types: frozenset[ConsentType],
        confirmed_by_user_id: UUID,
        confirmed_via: ConsentMethod,
        confirmed_at: datetime,
    ) -> list[ConsentRecordView]:
        del school_id, confirmed_by_user_id
        records = []
        for consent_type in consent_types:
            record = ConsentRecordView(
                id=uuid4(),
                student_id=student_id,
                consent_type=consent_type,
                status=ConsentStatus.CONFIRMED,
                confirmation_source=ConsentConfirmationSource.SCHOOL,
                confirmed_via=confirmed_via,
                confirmed_at=confirmed_at,
            )
            self.records[(student_id, consent_type)] = record
            records.append(record)
        return records

    async def create_parent_request(
        self,
        draft: ParentConsentRequestDraft,
    ) -> QueuedParentConsentRequest:
        self.requests[draft.token_digest] = draft
        self.links[draft.parent_link_id] = ParentLinkView(
            id=draft.parent_link_id,
            school_id=draft.school_id,
            student_id=draft.student_id,
            parent_id=None,
            parent_name=draft.parent_name,
            parent_contact=draft.parent_contact,
            contact_method=draft.contact_method,
            account_created=False,
        )
        return QueuedParentConsentRequest(
            invitation_id=draft.invitation_id,
            parent_link_id=draft.parent_link_id,
            student_id=draft.student_id,
            consent_types=draft.consent_types,
            delivery_status=ConsentDeliveryStatus.QUEUED,
            expires_at=draft.expires_at,
        )

    async def complete_parent_request(
        self,
        *,
        token_digest: str,
        completed_at: datetime,
    ) -> ParentConsentCompletion | None:
        draft = self.requests.get(token_digest)
        if draft is None or token_digest in self.completed_tokens:
            return None
        self.completed_tokens.add(token_digest)
        parent_id = uuid4()
        link = self.links[draft.parent_link_id]
        self.links[link.id] = replace(
            link,
            parent_id=parent_id,
            account_created=True,
        )
        for consent_type in draft.consent_types:
            self.records[(draft.student_id, consent_type)] = ConsentRecordView(
                id=uuid4(),
                student_id=draft.student_id,
                consent_type=consent_type,
                status=ConsentStatus.CONFIRMED,
                confirmation_source=ConsentConfirmationSource.PARENT,
                confirmed_via=ConsentMethod.DIGITAL,
                confirmed_at=completed_at,
            )
        return ParentConsentCompletion(
            invitation_id=draft.invitation_id,
            parent_link_id=draft.parent_link_id,
            parent_id=parent_id,
            student_id=draft.student_id,
            confirmed_types=draft.consent_types,
            completed_at=completed_at,
        )

    async def parent_links(
        self,
        *,
        school_id: UUID,
        student_id: UUID,
    ) -> list[ParentLinkView]:
        return [
            link
            for link in self.links.values()
            if link.school_id == school_id and link.student_id == student_id
        ]

    async def has_confirmed_consent(
        self,
        *,
        student_id: UUID,
        consent_type: ConsentType,
    ) -> bool:
        record = self.records.get((student_id, consent_type))
        return record is not None and record.status is ConsentStatus.CONFIRMED

    async def ensure_pending(
        self,
        *,
        student_id: UUID,
        consent_types: frozenset[ConsentType],
    ) -> None:
        self.pending_initializations.append((student_id, consent_types))
        for consent_type in consent_types:
            self.records.setdefault(
                (student_id, consent_type),
                ConsentRecordView(
                    id=uuid4(),
                    student_id=student_id,
                    consent_type=consent_type,
                    status=ConsentStatus.PENDING,
                    confirmation_source=None,
                    confirmed_via=None,
                    confirmed_at=None,
                ),
            )


class FixedConsentTokenService:
    token = "parent-consent-token-that-is-long-enough"
    digest_value = "fixed-token-digest"

    def issue(self) -> tuple[str, str]:
        return self.token, self.digest_value

    def digest(self, token: str) -> str:
        return self.digest_value if token == self.token else f"digest:{token}"
