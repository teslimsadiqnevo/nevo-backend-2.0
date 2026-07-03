from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from nevo.domain.permissions.vocabulary import PermissionScope
from nevo.domain.teacher_assignments.vocabulary import (
    TeacherAssignmentRole,
    TeacherAssignmentSource,
)
from nevo.permissions.entities import PermissionSnapshot
from nevo.teacher_assignments.entities import (
    RosterAssignmentBatch,
    RosterAssignmentCandidate,
)
from nevo.teacher_assignments.errors import (
    AssignmentNotFoundError,
    MissingSchoolContextError,
    TeacherNotAssignedError,
)
from nevo.teacher_assignments.service import (
    MANUAL_FALLBACK_MESSAGE,
    TeacherAssignmentService,
)

from .fakes import (
    FakeRosterAssignmentProvider,
    MemoryTeacherAssignmentRepository,
)

NOW = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)


@dataclass
class Clock:
    def __call__(self) -> datetime:
        return NOW


def actor(
    *,
    role: str = "other_admin",
    school: bool = True,
) -> PermissionSnapshot:
    return PermissionSnapshot(
        user_id=uuid4(),
        school_id=uuid4() if school else None,
        role=role,
        status="active",
        school_auth_method="email_password",
        assigned_scopes=frozenset({PermissionScope.ROSTER}),
    )


def service_for(
    batch: RosterAssignmentBatch | None = None,
) -> tuple[TeacherAssignmentService, MemoryTeacherAssignmentRepository]:
    repository = MemoryTeacherAssignmentRepository()
    service = TeacherAssignmentService(
        repository=repository,
        roster_provider=FakeRosterAssignmentProvider(
            batch or RosterAssignmentBatch(supported=False)
        ),
        now=Clock(),
    )
    return service, repository


async def test_manual_assignment_uses_actor_school_and_history_timestamp() -> None:
    current_actor = actor()
    service, _ = service_for()
    teacher_id = uuid4()
    class_id = uuid4()

    assignment = await service.assign(
        current_actor,
        teacher_id=teacher_id,
        class_id=class_id,
        role=TeacherAssignmentRole.PRIMARY,
    )

    assert assignment.school_id == current_actor.school_id
    assert assignment.teacher_id == teacher_id
    assert assignment.class_id == class_id
    assert assignment.source is TeacherAssignmentSource.MANUAL
    assert assignment.assigned_at == NOW


async def test_missing_school_context_is_rejected() -> None:
    service, _ = service_for()

    with pytest.raises(MissingSchoolContextError):
        await service.assign(
            actor(school=False),
            teacher_id=uuid4(),
            class_id=uuid4(),
            role=TeacherAssignmentRole.CO_TEACHER,
        )


async def test_reassignment_soft_removes_and_links_previous_assignment() -> None:
    current_actor = actor()
    service, repository = service_for()
    first = await service.assign(
        current_actor,
        teacher_id=uuid4(),
        class_id=uuid4(),
        role=TeacherAssignmentRole.PRIMARY,
    )

    replacement = await service.reassign(
        current_actor,
        assignment_id=first.id,
        new_teacher_id=uuid4(),
    )

    previous = repository.assignments[first.id]
    assert previous.removed_at == NOW
    assert previous.replaced_by_assignment_id == replacement.id
    assert replacement.role is TeacherAssignmentRole.PRIMARY


async def test_remove_unknown_assignment_is_not_silent() -> None:
    service, _ = service_for()

    with pytest.raises(AssignmentNotFoundError):
        await service.remove(actor(), assignment_id=uuid4())


async def test_teacher_assignment_constraint_is_reusable_for_lessons() -> None:
    current_actor = actor()
    service, _ = service_for()
    teacher_id = uuid4()
    class_id = uuid4()

    with pytest.raises(TeacherNotAssignedError):
        await service.require_teacher_assignment(
            current_actor,
            teacher_id=teacher_id,
            class_id=class_id,
        )

    await service.assign(
        current_actor,
        teacher_id=teacher_id,
        class_id=class_id,
        role=TeacherAssignmentRole.CO_TEACHER,
    )
    await service.require_teacher_assignment(
        current_actor,
        teacher_id=teacher_id,
        class_id=class_id,
    )


async def test_my_classes_returns_only_active_assignments() -> None:
    current_actor = actor(role="teacher")
    service, repository = service_for()
    class_id = uuid4()
    repository.class_names[class_id] = ("JSS 3", "JSS3")
    assignment = await service.assign(
        current_actor,
        teacher_id=current_actor.user_id,
        class_id=class_id,
        role=TeacherAssignmentRole.PRIMARY,
    )

    classes = await service.teacher_classes(
        current_actor,
        teacher_id=current_actor.user_id,
    )

    assert classes[0].assignment_id == assignment.id
    assert classes[0].class_name == "JSS 3"


async def test_unavailable_roster_returns_explicit_manual_fallback() -> None:
    service, _ = service_for(RosterAssignmentBatch(supported=False))

    outcome = await service.sync_from_roster(actor())

    assert outcome.status == "manual_fallback_required"
    assert outcome.imported_assignments == 0
    assert outcome.message == MANUAL_FALLBACK_MESSAGE


async def test_roster_sync_imports_mapped_rows_and_reports_missing_rows() -> None:
    mapped_teacher = uuid4()
    mapped_class = uuid4()
    service, repository = service_for(
        RosterAssignmentBatch(
            supported=True,
            assignments=(
                RosterAssignmentCandidate(
                    teacher_id=mapped_teacher,
                    class_id=mapped_class,
                    role=TeacherAssignmentRole.PRIMARY,
                    source_reference="sis-row-1",
                ),
                RosterAssignmentCandidate(
                    teacher_id=None,
                    class_id=uuid4(),
                    role=TeacherAssignmentRole.CO_TEACHER,
                    source_reference="sis-row-2",
                ),
            ),
        )
    )

    outcome = await service.sync_from_roster(actor())

    assert outcome.status == "partial_manual_fallback_required"
    assert outcome.imported_assignments == 1
    assert outcome.missing_mappings == 1
    imported = next(iter(repository.assignments.values()))
    assert imported.source is TeacherAssignmentSource.ROSTER_SYNC
