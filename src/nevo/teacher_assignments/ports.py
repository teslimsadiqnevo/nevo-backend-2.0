from datetime import datetime
from typing import Protocol
from uuid import UUID

from nevo.domain.teacher_assignments.vocabulary import (
    TeacherAssignmentRole,
    TeacherAssignmentSource,
)
from nevo.teacher_assignments.entities import (
    AssignedClass,
    AssignedTeacher,
    RosterAssignmentBatch,
    TeacherClassAssignment,
)


class TeacherAssignmentRepository(Protocol):
    async def assign(
        self,
        *,
        school_id: UUID,
        teacher_id: UUID,
        class_id: UUID,
        role: TeacherAssignmentRole,
        source: TeacherAssignmentSource,
        source_reference: str | None,
        assigned_by_user_id: UUID | None,
        assigned_at: datetime,
    ) -> TeacherClassAssignment: ...

    async def reassign(
        self,
        *,
        school_id: UUID,
        assignment_id: UUID,
        new_teacher_id: UUID,
        role: TeacherAssignmentRole | None,
        assigned_by_user_id: UUID,
        assigned_at: datetime,
    ) -> TeacherClassAssignment: ...

    async def remove(
        self,
        *,
        school_id: UUID,
        assignment_id: UUID,
        removed_at: datetime,
    ) -> bool: ...

    async def teacher_classes(
        self,
        *,
        school_id: UUID,
        teacher_id: UUID,
    ) -> list[AssignedClass]: ...

    async def class_teachers(
        self,
        *,
        school_id: UUID,
        class_id: UUID,
    ) -> list[AssignedTeacher]: ...

    async def is_teacher_assigned(
        self,
        *,
        school_id: UUID,
        teacher_id: UUID,
        class_id: UUID,
    ) -> bool: ...


class RosterAssignmentProvider(Protocol):
    async def assignments_for_school(
        self,
        school_id: UUID,
    ) -> RosterAssignmentBatch: ...
