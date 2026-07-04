from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from nevo.domain.accounts.vocabulary import (
    ConsentMethod,
    ConsentStatus,
    ConsentType,
)
from nevo.domain.consent.vocabulary import (
    ConsentConfirmationSource,
    ConsentDeliveryStatus,
    ParentContactMethod,
)


@dataclass(frozen=True, slots=True)
class ConsentActor:
    user_id: UUID
    school_id: UUID


@dataclass(frozen=True, slots=True)
class ConsentRecordView:
    id: UUID
    student_id: UUID
    consent_type: ConsentType
    status: ConsentStatus
    confirmation_source: ConsentConfirmationSource | None
    confirmed_via: ConsentMethod | None
    confirmed_at: datetime | None


@dataclass(frozen=True, slots=True)
class ParentLinkView:
    id: UUID
    school_id: UUID
    student_id: UUID
    parent_id: UUID | None
    parent_name: str
    parent_contact: str
    contact_method: ParentContactMethod
    account_created: bool


@dataclass(frozen=True, slots=True)
class ParentConsentRequestDraft:
    invitation_id: UUID
    parent_link_id: UUID
    school_id: UUID
    student_id: UUID
    parent_name: str
    parent_contact: str
    contact_method: ParentContactMethod
    consent_types: frozenset[ConsentType]
    token_digest: str
    consent_url: str
    requested_by_user_id: UUID
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class QueuedParentConsentRequest:
    invitation_id: UUID
    parent_link_id: UUID
    student_id: UUID
    consent_types: frozenset[ConsentType]
    delivery_status: ConsentDeliveryStatus
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ParentConsentCompletion:
    invitation_id: UUID
    parent_link_id: UUID
    parent_id: UUID
    student_id: UUID
    confirmed_types: frozenset[ConsentType]
    completed_at: datetime


@dataclass(frozen=True, slots=True)
class ConsentGate:
    student_id: UUID
    granted: bool
    required_type: ConsentType
    status: ConsentStatus
