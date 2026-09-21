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
