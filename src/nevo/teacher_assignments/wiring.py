from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.teacher_assignments.repositories import (
    SqlAlchemyTeacherAssignmentRepository,
)
from nevo.teacher_assignments.roster import UnavailableRosterAssignmentProvider
from nevo.teacher_assignments.service import TeacherAssignmentService


def build_teacher_assignment_service(
    sessions: async_sessionmaker[AsyncSession],
) -> TeacherAssignmentService:
    return TeacherAssignmentService(
        repository=SqlAlchemyTeacherAssignmentRepository(sessions),
        roster_provider=UnavailableRosterAssignmentProvider(),
    )
