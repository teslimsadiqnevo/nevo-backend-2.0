from enum import StrEnum


class FailureAttribution(StrEnum):
    CONCEPT = "concept"
    READING = "reading"
    MIXED = "mixed"
    NONE = "none"
