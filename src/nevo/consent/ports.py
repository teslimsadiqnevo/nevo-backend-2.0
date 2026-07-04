from datetime import datetime
from typing import Protocol
from uuid import UUID

from nevo.consent.entities import (
    ConsentRecordView,
    ParentConsentCompletion,
    ParentConsentRequestDraft,
    ParentLinkView,
    QueuedParentConsentRequest,
)
from nevo.domain.accounts.vocabulary import ConsentMethod, ConsentType


class ConsentRepository(Protocol):
    async def confirm_by_school(
        self,
        *,
        school_id: UUID,
        student_id: UUID,
        consent_types: frozenset[ConsentType],
        confirmed_by_user_id: UUID,
        confirmed_via: ConsentMethod,
        confirmed_at: datetime,
    ) -> list[ConsentRecordView]: ...

    async def create_parent_request(
        self,
        draft: ParentConsentRequestDraft,
    ) -> QueuedParentConsentRequest: ...

    async def complete_parent_request(
        self,
        *,
        token_digest: str,
        completed_at: datetime,
    ) -> ParentConsentCompletion | None: ...

    async def parent_links(
        self,
        *,
        school_id: UUID,
        student_id: UUID,
    ) -> list[ParentLinkView]: ...

    async def has_confirmed_consent(
        self,
        *,
        student_id: UUID,
        consent_type: ConsentType,
    ) -> bool: ...

    async def ensure_pending(
        self,
        *,
        student_id: UUID,
        consent_types: frozenset[ConsentType],
    ) -> None: ...


class ConsentTokenService(Protocol):
    def issue(self) -> tuple[str, str]: ...

    def digest(self, token: str) -> str: ...
