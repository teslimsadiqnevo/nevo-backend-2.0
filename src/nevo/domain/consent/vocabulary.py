from enum import StrEnum


class ParentContactMethod(StrEnum):
    EMAIL = "email"
    SMS = "sms"


class ConsentConfirmationSource(StrEnum):
    SCHOOL = "school"
    PARENT = "parent"


class ConsentDeliveryStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"
