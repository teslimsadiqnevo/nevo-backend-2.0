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
