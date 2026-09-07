from datetime import datetime
from typing import Protocol
from uuid import UUID

from nevo.consent.entities import (
    ConsentRecordView,
    ParentConsentCompletion,
    ParentConsentRequestDraft,
    ParentInvitationView,
    ParentLinkView,
    ParentRightOutcome,
    QueuedParentConsentRequest,
)
from nevo.domain.accounts.vocabulary import ConsentMethod, ConsentStatus, ConsentType
from nevo.domain.consent.vocabulary import ParentRightType


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

    async def parent_invitation(
        self,
        *,
        token_digest: str,
        now: datetime,
    ) -> ParentInvitationView | None: ...

    async def exercise_parent_right(
        self,
        *,
        token_digest: str,
        request_type: ParentRightType,
        reason: str | None,
        now: datetime,
    ) -> ParentRightOutcome | None: ...

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

    async def consent_status(
        self,
        *,
        student_id: UUID,
        consent_type: ConsentType,
    ) -> ConsentStatus: ...

    async def ensure_pending(
        self,
        *,
        student_id: UUID,
        consent_types: frozenset[ConsentType],
    ) -> None: ...


class ConsentTokenService(Protocol):
    def issue(self) -> tuple[str, str]: ...

    def digest(self, token: str) -> str: ...
