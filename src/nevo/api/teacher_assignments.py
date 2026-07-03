from dataclasses import asdict
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from nevo.api.permissions import RequireScope
from nevo.domain.permissions.vocabulary import PermissionScope
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
    AssignmentConflictError,
    AssignmentNotFoundError,
    ClassNotFoundError,
    MissingSchoolContextError,
    PrimaryTeacherExistsError,
    TeacherAssignmentError,
    TeacherNotAssignedError,
    TeacherNotFoundError,
)
from nevo.teacher_assignments.service import TeacherAssignmentService

router = APIRouter(prefix="/api/v1", tags=["teacher assignments"])


class CreateAssignmentRequest(BaseModel):
    teacher_id: UUID
    class_id: UUID
    role: TeacherAssignmentRole


class ReassignRequest(BaseModel):
    new_teacher_id: UUID
    role: TeacherAssignmentRole | None = None


class AssignmentResponse(BaseModel):
    id: UUID
    school_id: UUID
    teacher_id: UUID
    class_id: UUID
    role: TeacherAssignmentRole
    source: TeacherAssignmentSource
    assigned_at: datetime

    @classmethod
    def from_assignment(
        cls,
        assignment: TeacherClassAssignment,
    ) -> "AssignmentResponse":
        return cls(
            id=assignment.id,
            school_id=assignment.school_id,
            teacher_id=assignment.teacher_id,
            class_id=assignment.class_id,
            role=assignment.role,
            source=assignment.source,
            assigned_at=assignment.assigned_at,
        )


class AssignedClassResponse(BaseModel):
    assignment_id: UUID
    class_id: UUID
    class_name: str
    class_code: str | None
    role: TeacherAssignmentRole
    assigned_at: datetime

    @classmethod
    def from_assigned_class(cls, item: AssignedClass) -> "AssignedClassResponse":
        return cls(**asdict(item))


class AssignedTeacherResponse(BaseModel):
    assignment_id: UUID
    teacher_id: UUID
    first_name: str | None
    last_name: str | None
    email: str | None
    role: TeacherAssignmentRole
    assigned_at: datetime

    @classmethod
    def from_assigned_teacher(
        cls,
        item: AssignedTeacher,
    ) -> "AssignedTeacherResponse":
        return cls(**asdict(item))


class RosterSyncResponse(BaseModel):
    status: str
    imported_assignments: int
    missing_mappings: int
    message: str

    @classmethod
    def from_outcome(cls, outcome: RosterSyncOutcome) -> "RosterSyncResponse":
        return cls(
            status=outcome.status,
            imported_assignments=outcome.imported_assignments,
            missing_mappings=outcome.missing_mappings,
            message=outcome.message,
        )


def get_teacher_assignment_service(request: Request) -> TeacherAssignmentService:
    service = getattr(request.app.state, "teacher_assignment_service", None)
    if not isinstance(service, TeacherAssignmentService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_unavailable",
                "message": "Teacher assignments are temporarily unavailable.",
            },
        )
    return service


TeacherAssignmentServiceDependency = Annotated[
    TeacherAssignmentService,
    Depends(get_teacher_assignment_service),
]
RosterDependency = Annotated[
    PermissionSnapshot,
    Depends(RequireScope(PermissionScope.ROSTER)),
]
TeacherDependency = Annotated[
    PermissionSnapshot,
    Depends(RequireScope(PermissionScope.TEACHER)),
]
ItSsoDependency = Annotated[
    PermissionSnapshot,
    Depends(RequireScope(PermissionScope.IT_SSO)),
]


@router.post(
    "/teacher-class-assignments",
    response_model=AssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_assignment(
    payload: CreateAssignmentRequest,
    actor: RosterDependency,
    service: TeacherAssignmentServiceDependency,
) -> AssignmentResponse:
    try:
        assignment = await service.assign(
            actor,
            teacher_id=payload.teacher_id,
            class_id=payload.class_id,
            role=payload.role,
        )
    except TeacherAssignmentError as error:
        raise public_assignment_error(error) from error
    return AssignmentResponse.from_assignment(assignment)


@router.post(
    "/teacher-class-assignments/{assignment_id}/reassign",
    response_model=AssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def reassign_teacher(
    assignment_id: UUID,
    payload: ReassignRequest,
    actor: RosterDependency,
    service: TeacherAssignmentServiceDependency,
) -> AssignmentResponse:
    try:
        assignment = await service.reassign(
            actor,
            assignment_id=assignment_id,
            new_teacher_id=payload.new_teacher_id,
            role=payload.role,
        )
    except TeacherAssignmentError as error:
        raise public_assignment_error(error) from error
    return AssignmentResponse.from_assignment(assignment)


@router.delete(
    "/teacher-class-assignments/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_assignment(
    assignment_id: UUID,
    actor: RosterDependency,
    service: TeacherAssignmentServiceDependency,
) -> None:
    try:
        await service.remove(actor, assignment_id=assignment_id)
    except TeacherAssignmentError as error:
        raise public_assignment_error(error) from error


@router.get(
    "/teachers/me/classes",
    response_model=list[AssignedClassResponse],
)
async def my_classes(
    actor: TeacherDependency,
    service: TeacherAssignmentServiceDependency,
) -> list[AssignedClassResponse]:
    classes = await service.teacher_classes(actor, teacher_id=actor.user_id)
    return [AssignedClassResponse.from_assigned_class(item) for item in classes]


@router.get(
    "/teachers/{teacher_id}/classes",
    response_model=list[AssignedClassResponse],
)
async def teacher_classes(
    teacher_id: UUID,
    actor: RosterDependency,
    service: TeacherAssignmentServiceDependency,
) -> list[AssignedClassResponse]:
    classes = await service.teacher_classes(actor, teacher_id=teacher_id)
    return [AssignedClassResponse.from_assigned_class(item) for item in classes]


@router.get(
    "/classes/{class_id}/teachers",
    response_model=list[AssignedTeacherResponse],
)
async def class_teachers(
    class_id: UUID,
    actor: RosterDependency,
    service: TeacherAssignmentServiceDependency,
) -> list[AssignedTeacherResponse]:
    teachers = await service.class_teachers(actor, class_id=class_id)
    return [
        AssignedTeacherResponse.from_assigned_teacher(item)
        for item in teachers
    ]


@router.post(
    "/teacher-class-assignments/roster-sync",
    response_model=RosterSyncResponse,
)
async def sync_roster_assignments(
    actor: ItSsoDependency,
    service: TeacherAssignmentServiceDependency,
) -> RosterSyncResponse:
    try:
        outcome = await service.sync_from_roster(actor)
    except TeacherAssignmentError as error:
        raise public_assignment_error(error) from error
    return RosterSyncResponse.from_outcome(outcome)


def public_assignment_error(error: TeacherAssignmentError) -> HTTPException:
    status_code = status.HTTP_400_BAD_REQUEST
    if isinstance(
        error,
        (
            AssignmentNotFoundError,
            ClassNotFoundError,
            TeacherNotFoundError,
        ),
    ):
        status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(
        error,
        (
            AssignmentConflictError,
            PrimaryTeacherExistsError,
        ),
    ):
        status_code = status.HTTP_409_CONFLICT
    elif isinstance(
        error,
        (
            MissingSchoolContextError,
            TeacherNotAssignedError,
        ),
    ):
        status_code = status.HTTP_403_FORBIDDEN
    return HTTPException(
        status_code=status_code,
        detail={
            "code": error.code,
            "message": error.public_message,
        },
    )
