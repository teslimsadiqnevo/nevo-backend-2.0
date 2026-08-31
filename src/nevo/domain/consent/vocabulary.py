from enum import StrEnum


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
