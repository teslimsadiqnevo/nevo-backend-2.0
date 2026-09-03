from enum import StrEnum


class PartnerInquiryRole(StrEnum):
    """Who is asking.

    TEACHER and PARENT come from the TOSSE dropdown in SCRUM-117 - a stand at
    a schools expo gets both, and without them either would have been recorded
    as "other".
    """

    SCHOOL_OWNER = "school_owner"
    PROPRIETOR = "proprietor"
    SENCO = "senco"
    HEAD_OF_LEARNING = "head_of_learning"
    HEAD_TEACHER = "head_teacher"
    TEACHER = "teacher"
    PARENT = "parent"
    OTHER = "other"


#: The TOSSE dropdown sends its display label, not a snake_case value. Mapping
#: it here rather than asking the page to translate keeps the label the visitor
#: actually chose as the single source of truth.
ROLE_LABELS: dict[str, PartnerInquiryRole] = {
    "school proprietor / owner": PartnerInquiryRole.PROPRIETOR,
    "academic director / head of school": PartnerInquiryRole.HEAD_OF_LEARNING,
    "teacher": PartnerInquiryRole.TEACHER,
    "parent": PartnerInquiryRole.PARENT,
    "other": PartnerInquiryRole.OTHER,
}


def parse_role(value: str) -> PartnerInquiryRole | None:
    """Accept a display label or a stored value; None when neither matches.

    A lead is worth more than a tidy enum, so an unrecognised role is not a
    reason to reject the submission - the caller falls back to OTHER.
    """
    cleaned = " ".join(value.split()).strip().casefold()
    if cleaned in ROLE_LABELS:
        return ROLE_LABELS[cleaned]
    try:
        return PartnerInquiryRole(cleaned.replace(" ", "_"))
    except ValueError:
        return None


class PartnerInquiryContactMethod(StrEnum):
    EMAIL = "email"
    PHONE = "phone"


class PartnerInquirySource(StrEnum):
    """Where a lead came from, so an event's leads can be pulled out later."""

    WEBSITE = "website"
    TOSSE_2026 = "tosse_2026"


class PartnerInquiryIntent(StrEnum):
    """What the school is asking for.

    The first three are the TOSSE card selector, confirmed against SCRUM-117.
    PILOT and LEARN_MORE predate it and are kept so the website form keeps
    working.
    """

    FOUNDING_PARTNER = "founding_partner"
    SCHEDULE_WALKTHROUGH = "schedule_walkthrough"
    CONTACT_ME = "contact_me"
    PILOT = "pilot"
    LEARN_MORE = "learn_more"
