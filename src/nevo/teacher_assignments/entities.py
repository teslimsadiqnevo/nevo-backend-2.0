from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from nevo.domain.teacher_assignments.vocabulary import (
    TeacherAssignmentRole,
    TeacherAssignmentSource,
)


@dataclass(frozen=True, slots=True)
class TeacherClassAssignment:
    id: UUID
    school_id: UUID
    teacher_id: UUID
    class_id: UUID
    role: TeacherAssignmentRole
    source: TeacherAssignmentSource
    assigned_at: datetime
    removed_at: datetime | None = None
    replaced_by_assignment_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class AssignedClass:
    assignment_id: UUID
    class_id: UUID
    class_name: str
    class_code: str | None
    role: TeacherAssignmentRole
    assigned_at: datetime


@dataclass(frozen=True, slots=True)
class AssignedTeacher:
    assignment_id: UUID
    teacher_id: UUID
    first_name: str | None
    last_name: str | None
    email: str | None
    role: TeacherAssignmentRole
    assigned_at: datetime


@dataclass(frozen=True, slots=True)
class RosterAssignmentCandidate:
    teacher_id: UUID | None
    class_id: UUID | None
    role: TeacherAssignmentRole
    source_reference: str | None = None


@dataclass(frozen=True, slots=True)
class RosterAssignmentBatch:
    supported: bool
    assignments: tuple[RosterAssignmentCandidate, ...] = ()


@dataclass(frozen=True, slots=True)
class RosterSyncOutcome:
    status: str
    imported_assignments: int
    missing_mappings: int
    message: str
