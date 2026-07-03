from dataclasses import replace
from datetime import datetime
from uuid import UUID, uuid4

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
from nevo.teacher_assignments.errors import (
    AssignmentConflictError,
    AssignmentNotFoundError,
    PrimaryTeacherExistsError,
)


class MemoryTeacherAssignmentRepository:
    def __init__(self) -> None:
        self.assignments: dict[UUID, TeacherClassAssignment] = {}
        self.class_names: dict[UUID, tuple[str, str | None]] = {}
        self.teacher_names: dict[
            UUID,
            tuple[str | None, str | None, str | None],
        ] = {}

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
    ) -> TeacherClassAssignment:
        del source_reference, assigned_by_user_id
        active = [
            item
            for item in self.assignments.values()
            if item.school_id == school_id
            and item.class_id == class_id
            and item.removed_at is None
        ]
        duplicate = next(
            (item for item in active if item.teacher_id == teacher_id),
            None,
        )
        if duplicate is not None:
            if duplicate.role is role:
                return duplicate
            raise AssignmentConflictError
        if role is TeacherAssignmentRole.PRIMARY and any(
            item.role is TeacherAssignmentRole.PRIMARY for item in active
        ):
            raise PrimaryTeacherExistsError
        assignment = TeacherClassAssignment(
            id=uuid4(),
            school_id=school_id,
            teacher_id=teacher_id,
            class_id=class_id,
            role=role,
            source=source,
            assigned_at=assigned_at,
        )
        self.assignments[assignment.id] = assignment
        return assignment

    async def reassign(
        self,
        *,
        school_id: UUID,
        assignment_id: UUID,
        new_teacher_id: UUID,
        role: TeacherAssignmentRole | None,
        assigned_by_user_id: UUID,
        assigned_at: datetime,
    ) -> TeacherClassAssignment:
        del assigned_by_user_id
        current = self.assignments.get(assignment_id)
        if (
            current is None
            or current.school_id != school_id
            or current.removed_at is not None
        ):
            raise AssignmentNotFoundError
        replacement = TeacherClassAssignment(
            id=uuid4(),
            school_id=school_id,
            teacher_id=new_teacher_id,
            class_id=current.class_id,
            role=role or current.role,
            source=TeacherAssignmentSource.MANUAL,
            assigned_at=assigned_at,
        )
        self.assignments[current.id] = replace(
            current,
            removed_at=assigned_at,
            replaced_by_assignment_id=replacement.id,
        )
        self.assignments[replacement.id] = replacement
        return replacement

    async def remove(
        self,
        *,
        school_id: UUID,
        assignment_id: UUID,
        removed_at: datetime,
    ) -> bool:
        current = self.assignments.get(assignment_id)
        if (
            current is None
            or current.school_id != school_id
            or current.removed_at is not None
        ):
            return False
        self.assignments[current.id] = replace(current, removed_at=removed_at)
        return True

    async def teacher_classes(
        self,
        *,
        school_id: UUID,
        teacher_id: UUID,
    ) -> list[AssignedClass]:
        return [
            AssignedClass(
                assignment_id=item.id,
                class_id=item.class_id,
                class_name=self.class_names.get(
                    item.class_id,
                    ("Class", None),
                )[0],
                class_code=self.class_names.get(
                    item.class_id,
                    ("Class", None),
                )[1],
                role=item.role,
                assigned_at=item.assigned_at,
            )
            for item in self.assignments.values()
            if item.school_id == school_id
            and item.teacher_id == teacher_id
            and item.removed_at is None
        ]

    async def class_teachers(
        self,
        *,
        school_id: UUID,
        class_id: UUID,
    ) -> list[AssignedTeacher]:
        return [
            AssignedTeacher(
                assignment_id=item.id,
                teacher_id=item.teacher_id,
                first_name=self.teacher_names.get(
                    item.teacher_id,
                    (None, None, None),
                )[0],
                last_name=self.teacher_names.get(
                    item.teacher_id,
                    (None, None, None),
                )[1],
                email=self.teacher_names.get(
                    item.teacher_id,
                    (None, None, None),
                )[2],
                role=item.role,
                assigned_at=item.assigned_at,
            )
            for item in self.assignments.values()
            if item.school_id == school_id
            and item.class_id == class_id
            and item.removed_at is None
        ]

    async def is_teacher_assigned(
        self,
        *,
        school_id: UUID,
        teacher_id: UUID,
        class_id: UUID,
    ) -> bool:
        return any(
            item.school_id == school_id
            and item.teacher_id == teacher_id
            and item.class_id == class_id
            and item.removed_at is None
            for item in self.assignments.values()
        )


class FakeRosterAssignmentProvider:
    def __init__(self, batch: RosterAssignmentBatch) -> None:
        self.batch = batch

    async def assignments_for_school(
        self,
        school_id: UUID,
    ) -> RosterAssignmentBatch:
        del school_id
        return self.batch
