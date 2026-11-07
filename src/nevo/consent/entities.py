from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from nevo.domain.accounts.vocabulary import (
    ConsentMethod,
    ConsentStatus,
    ConsentType,
    UserStatus,
)
from nevo.domain.consent.vocabulary import (
    AgeCheckState,
    ConsentConfirmationSource,
    ConsentDeliveryStatus,
    ParentContactMethod,
    ParentRightType,
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
class ParentRightLogEntry:
    """One right a parent exercised, for the school's own record.

    NDPA requires a school to be able to show what was asked of it and when.
    The parent's stated reason is deliberately reduced to whether one was
    given: it is free text a parent wrote about their own child, and a log
    that lists it turns a rights record into a disclosure of family
    circumstances to every admin who opens the screen.
    """

    id: UUID
    student_id: UUID
    student_name: str
    parent_id: UUID
    parent_name: str
    request_type: ParentRightType
    reason_recorded: bool
    status: str
    created_at: datetime
    resolved_at: datetime | None


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
    #: Asked for and not granted. A parent who ticks one box and not another
    #: has answered both, and the screen should be able to say so rather than
    #: showing the second as still outstanding.
    declined_types: frozenset[ConsentType] = frozenset()
    #: What comparing the parent's date of birth with the school's produced.
    age_check: AgeCheckState = AgeCheckState.AWAITING_PARENT
    #: Where the parent's copy was sent, so the page states a fact rather
    #: than a hope. None when we hold no contact to send one to.
    receipt_sent_to: ParentContactMethod | None = None


@dataclass(frozen=True, slots=True)
class ConsentGate:
    """Whether a learner may proceed, and whether consent has been recorded.

    SCRUM-257 requires affirmative confirmed processing consent. ``granted``
    is true only then, and ``blocked`` is its inverse. The stored status still
    distinguishes withdrawal from consent that has not yet been confirmed.
    """

    student_id: UUID
    granted: bool
    blocked: bool
    required_type: ConsentType
    status: ConsentStatus


@dataclass(frozen=True, slots=True)
class ParentInvitationView:
    """What a parent may see before they decide, resolved from their token.

    Named for the child and the school on purpose. A consent screen that says
    "your child's school" has not told the parent which child or which school,
    and NDPA s.31 consent given against that is not informed.
    """

    invitation_id: UUID
    student_id: UUID
    student_first_name: str
    school_name: str
    school_phone: str | None
    school_email: str | None
    parent_name: str
    #: The address or number the school holds, so the setup screen can
    #: pre-fill "your email, from your school's records" rather than ask a
    #: parent to guess which one we have.
    parent_contact: str
    parent_contact_method: ParentContactMethod
    status: ConsentStatus
    consent_types: frozenset[ConsentType]
    expires_at: datetime
    decided_at: datetime | None
    #: Whether this guardian already has an account they can sign in to, so a
    #: returning parent is sent to sign in rather than through setting a
    #: password they already have. Without it the screen could only guess from
    #: the consent status, which says nothing about the account.
    parent_account_ready: bool = False
    #: Where the child's date of birth stands between the school and this
    #: parent, or None when no check has been raised. A parent arriving on a
    #: held child needs the recheck screen, not the consent form, and the
    #: token read was the only thing they had to route on.
    age_check_state: AgeCheckState | None = None
    #: Why it is held, when it is. enrolled_age_band_unavailable is a gap in
    #: the school's roster rather than a disagreement between the two adults,
    #: so a screen can say which of the two this is.
    age_check_hold_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ParentRightOutcome:
    request_id: UUID
    request_type: ParentRightType
    status: str
    reason_recorded: bool


@dataclass(frozen=True, slots=True)
class ParentAccount:
    """The account a parent can actually sign in with.

    ``contact`` is whatever their school holds - an email address or a phone
    number. The parent did not choose which, so the sign-in screen should ask
    for either rather than making them guess.
    """

    user_id: UUID
    contact: str
    contact_method: ParentContactMethod
    student_id: UUID
    already_active: bool


@dataclass(frozen=True, slots=True)
class ParentChildView:
    """One learner a signed-in parent is entitled to see."""

    student_id: UUID
    first_name: str | None
    last_name: str | None
    status: UserStatus
    school_id: UUID
    school_name: str
