from enum import StrEnum

from nevo.domain.accounts.vocabulary import ConsentType


class ParentContactMethod(StrEnum):
    """How Nevo reaches a parent. Email, and nothing else.

    SMS was removed on 20 September by ruling. You cannot collect personal
    data you have no use for: four hundred parents' phone numbers that nothing
    ever sends to are four hundred pieces of personal data with no lawful
    purpose, sitting in a database that has to be protected, purged and
    accounted for in the Data Sharing Agreement. "We might need it later" is
    not a purpose.

    Deliverability was the argument for keeping it. The written consent route
    answers that better: a parent who does not answer email gets a paper form
    in their child's bag.

    The enum keeps one member rather than being deleted, because a contact
    method is still a fact a consent record states, and a record that states
    nothing cannot say how a parent was reached.
    """

    EMAIL = "email"


class ConsentConfirmationSource(StrEnum):
    SCHOOL = "school"
    PARENT = "parent"


class ConsentNotificationKind(StrEnum):
    """What an outbox row is for: asking, or confirming afterwards."""

    REQUEST = "request"
    RECEIPT = "receipt"


class ConsentDeliveryStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"


class ParentRightType(StrEnum):
    """The data-subject rights a parent can exercise from the consent screen.

    Enumerated rather than pattern-matched so a generated client cannot invent
    a fourth value: these were previously discoverable only by sending a bad
    one and reading the rejection.
    """

    REQUEST_DATA = "request_data"
    OBJECT = "object"
    WITHDRAW_CONSENT = "withdraw_consent"


REQUIRED_LEARNING_CONSENT = ConsentType.DATA_PROCESSING
"""The one consent a learner cannot start without."""


class AgeCheckState(StrEnum):
    """Where a child's date of birth stands between two sources.

    The school gives one on the roster and the parent gives one when they
    consent. They are compared rather than trusted, because a date of birth
    decides whether a child is old enough for the product to be offered to
    them at all, and a single unverified source is not a check.
    """

    #: Both sources agree. Nothing to do and nobody is told.
    MATCHED = "matched"
    #: They disagree. Access is blocked until a person settles it with both
    #: the school and the parent.
    MISMATCH = "mismatch"
    #: A person settled it and recorded what was agreed.
    RESOLVED = "resolved"
    #: The parent has not confirmed one yet.
    AWAITING_PARENT = "awaiting_parent"


class ConsentRefusalReason(StrEnum):
    """Why Nevo stopped asking a parent.

    A refusal is kept after the learner's roster data goes, so the school
    does not invite the same parent again. It is the minimum that can carry
    that meaning: which child, a fingerprint of the address, and this.
    """

    #: Thirty days passed and nobody answered.
    NO_RESPONSE = "no_response"
    #: The parent said no.
    DECLINED = "declined"
    #: The parent consented and later withdrew.
    WITHDRAWN = "withdrawn"
