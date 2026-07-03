from enum import StrEnum


class TeacherAssignmentRole(StrEnum):
    PRIMARY = "primary"
    CO_TEACHER = "co_teacher"


class TeacherAssignmentSource(StrEnum):
    MANUAL = "manual"
    ROSTER_SYNC = "roster_sync"
