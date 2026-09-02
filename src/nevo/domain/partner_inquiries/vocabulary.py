from enum import StrEnum


class PartnerInquiryRole(StrEnum):
    SCHOOL_OWNER = "school_owner"
    PROPRIETOR = "proprietor"
    SENCO = "senco"
    HEAD_OF_LEARNING = "head_of_learning"
    HEAD_TEACHER = "head_teacher"
    OTHER = "other"


class PartnerInquiryContactMethod(StrEnum):
    EMAIL = "email"
    PHONE = "phone"


class PartnerInquirySource(StrEnum):
    """Where a lead came from, so an event's leads can be pulled out later."""

    WEBSITE = "website"
    TOSSE_2026 = "tosse_2026"


class PartnerInquiryIntent(StrEnum):
    """What the school is asking for.

    PLACEHOLDER - these three values must match the card selector on the
    landing page exactly. Confirm against SCRUM-117 before the QR code is
    printed; changing them is a one-line edit here plus a migration.
    """

    FOUNDING_PARTNER = "founding_partner"
    PILOT = "pilot"
    LEARN_MORE = "learn_more"
