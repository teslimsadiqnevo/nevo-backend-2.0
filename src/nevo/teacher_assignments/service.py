from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from nevo.domain.teacher_assignments.vocabulary import (
    TeacherAssignmentRole,
    TeacherAssignmentSource,
)
from nevo.permissions.entities import PermissionSnapshot
from nevo.teacher_assignments.entities import (
    AssignedClass,
    AssignedTeacher,
    RosterSyncOutcome,
    TeacherClassAssignment,
)
from nevo.teacher_assignments.errors import (
    AssignmentNotFoundError,
    MissingSchoolContextError,
    TeacherNotAssignedError,
)
from nevo.teacher_assignments.ports import (
    RosterAssignmentProvider,
    TeacherAssignmentRepository,
)

MANUAL_FALLBACK_MESSAGE = (
    "Roster mappings were not found. Assign teachers manually from the class "
    "or teacher detail page."
)


class TeacherAssignmentService:
    def __init__(
        self,
        *,
        repository: TeacherAssignmentRepository,
        roster_provider: RosterAssignmentProvider,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._roster_provider = roster_provider
        self._now = now or (lambda: datetime.now(UTC))

    async def assign(
        self,
        actor: PermissionSnapshot,
        *,
        teacher_id: UUID,
        class_id: UUID,
        role: TeacherAssignmentRole,
    ) -> TeacherClassAssignment:
        school_id = self._school_id(actor)
        return await self._repository.assign(
            school_id=school_id,
            teacher_id=teacher_id,
            class_id=class_id,
            role=role,
            source=TeacherAssignmentSource.MANUAL,
            source_reference=None,
            assigned_by_user_id=actor.user_id,
            assigned_at=self._now(),
        )

    async def reassign(
        self,
        actor: PermissionSnapshot,
        *,
        assignment_id: UUID,
        new_teacher_id: UUID,
        role: TeacherAssignmentRole | None = None,
    ) -> TeacherClassAssignment:
        return await self._repository.reassign(
            school_id=self._school_id(actor),
            assignment_id=assignment_id,
            new_teacher_id=new_teacher_id,
            role=role,
            assigned_by_user_id=actor.user_id,
            assigned_at=self._now(),
        )

    async def remove(
        self,
        actor: PermissionSnapshot,
        *,
        assignment_id: UUID,
    ) -> None:
        removed = await self._repository.remove(
            school_id=self._school_id(actor),
            assignment_id=assignment_id,
            removed_at=self._now(),
        )
        if not removed:
            raise AssignmentNotFoundError

    async def teacher_classes(
        self,
        actor: PermissionSnapshot,
        *,
        teacher_id: UUID,
    ) -> list[AssignedClass]:
        return await self._repository.teacher_classes(
            school_id=self._school_id(actor),
            teacher_id=teacher_id,
        )

    async def class_teachers(
        self,
        actor: PermissionSnapshot,
        *,
        class_id: UUID,
    ) -> list[AssignedTeacher]:
        return await self._repository.class_teachers(
            school_id=self._school_id(actor),
            class_id=class_id,
        )

    async def require_teacher_assignment(
        self,
        actor: PermissionSnapshot,
        *,
        teacher_id: UUID,
        class_id: UUID,
    ) -> None:
        assigned = await self._repository.is_teacher_assigned(
            school_id=self._school_id(actor),
            teacher_id=teacher_id,
            class_id=class_id,
        )
        if not assigned:
            raise TeacherNotAssignedError

    async def sync_from_roster(
        self,
        actor: PermissionSnapshot,
    ) -> RosterSyncOutcome:
        school_id = self._school_id(actor)
        batch = await self._roster_provider.assignments_for_school(school_id)
        if not batch.supported:
            return RosterSyncOutcome(
                status="manual_fallback_required",
                imported_assignments=0,
                missing_mappings=0,
                message=MANUAL_FALLBACK_MESSAGE,
            )

        imported = 0
        missing = 0
        for candidate in batch.assignments:
            if candidate.teacher_id is None or candidate.class_id is None:
                missing += 1
                continue
            await self._repository.assign(
                school_id=school_id,
                teacher_id=candidate.teacher_id,
                class_id=candidate.class_id,
                role=candidate.role,
                source=TeacherAssignmentSource.ROSTER_SYNC,
                source_reference=candidate.source_reference,
                assigned_by_user_id=None,
                assigned_at=self._now(),
            )
            imported += 1

        requires_fallback = missing > 0
        return RosterSyncOutcome(
            status=(
                "partial_manual_fallback_required"
                if requires_fallback
                else "completed"
            ),
            imported_assignments=imported,
            missing_mappings=missing,
            message=(
                MANUAL_FALLBACK_MESSAGE
                if requires_fallback
                else "Roster teacher assignments are up to date."
            ),
        )

    @staticmethod
    def _school_id(actor: PermissionSnapshot) -> UUID:
        if actor.school_id is None:
            raise MissingSchoolContextError
        return actor.school_id
