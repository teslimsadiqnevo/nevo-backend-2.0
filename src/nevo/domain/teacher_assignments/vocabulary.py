from enum import StrEnum


class TeacherAssignmentRole(StrEnum):
    PRIMARY = "primary"
    CO_TEACHER = "co_teacher"


class TeacherAssignmentSource(StrEnum):
    MANUAL = "manual"
    ROSTER_SYNC = "roster_sync"


class TeacherRosterSyncStatus(StrEnum):
    """Outcome of importing teacher-class assignments from a roster.

    Distinct from the SSO-level RosterSyncStatus: this one describes whether
    the teacher mappings landed, and both fallback states mean an admin still
    has work to do.
    """

    COMPLETED = "completed"
    PARTIAL_MANUAL_FALLBACK_REQUIRED = "partial_manual_fallback_required"
    MANUAL_FALLBACK_REQUIRED = "manual_fallback_required"
