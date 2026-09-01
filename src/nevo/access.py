from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.db.models.account import Class, StudentClassEnrollment, User
from nevo.db.models.teacher_assignment import TeacherClassAssignment
from nevo.domain.accounts.vocabulary import UserRole, UserStatus


async def accessible_students(session: AsyncSession, actor: User) -> list[User]:
    """Every learner this actor may see.

    One definition, used for two things that must not disagree: which names to
    pseudonymise before a prompt leaves the building, and which learners a tool
    may resolve. When those two sets differ, a name either reaches a provider
    unmasked or a learner the user can legitimately ask about becomes
    unreachable.

    Bounded by class for a teacher, so it stays a handful of rows rather than
    the whole school.
    """
    if actor.role is UserRole.STUDENT:
        return [actor]
    if actor.school_id is None:
        return []
    query = select(User).where(
        User.school_id == actor.school_id,
        User.role == UserRole.STUDENT,
        User.status != UserStatus.DEACTIVATED,
    )
    if actor.role is UserRole.TEACHER:
        query = (
            query.join(
                StudentClassEnrollment,
                StudentClassEnrollment.student_id == User.id,
            )
            .join(
                TeacherClassAssignment,
                TeacherClassAssignment.class_id == StudentClassEnrollment.class_id,
            )
            .where(
                TeacherClassAssignment.teacher_id == actor.id,
                TeacherClassAssignment.removed_at.is_(None),
            )
            .distinct()
        )
    return list((await session.scalars(query)).all())


async def accessible_classes(session: AsyncSession, actor: User) -> list[Class]:
    """Classes this actor may ask about, by the same derive-then-filter rule."""
    if actor.school_id is None or actor.role is UserRole.STUDENT:
        return []
    query = select(Class).where(
        Class.school_id == actor.school_id,
        Class.archived_at.is_(None),
    )
    if actor.role is UserRole.TEACHER:
        query = (
            query.join(
                TeacherClassAssignment,
                TeacherClassAssignment.class_id == Class.id,
            )
            .where(
                TeacherClassAssignment.teacher_id == actor.id,
                TeacherClassAssignment.removed_at.is_(None),
            )
            .distinct()
        )
    return list((await session.scalars(query.order_by(Class.name))).all())
