from enum import StrEnum

from nevo.domain.accounts.vocabulary import ConsentType


class ParentContactMethod(StrEnum):
    EMAIL = "email"
    SMS = "sms"


class ConsentConfirmationSource(StrEnum):
    SCHOOL = "school"
    PARENT = "parent"


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
