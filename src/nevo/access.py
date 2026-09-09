from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.db.models.account import Class, StudentClassEnrollment, User
from nevo.db.models.content import Lesson
from nevo.db.models.frontend_support import LessonAssignment
from nevo.db.models.teacher_assignment import TeacherClassAssignment
from nevo.domain.accounts.vocabulary import UserRole, UserStatus
from nevo.domain.intelligence.vocabulary import LessonScope


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


async def accessible_lessons(
    session: AsyncSession,
    actor: User,
    *,
    scope: LessonScope | None = None,
    limit: int | None = None,
) -> list[Lesson]:
    """The lessons this actor should be shown, by the same rule everywhere.

    A learner sees what has been assigned to them. A teacher's own view is
    wider than authorship: a lesson a colleague wrote but that this teacher
    assigns, or that goes to a class they teach, is theirs to look at too.
    Filtering on authorship alone would hide the lessons they actually teach.
    """
    if actor.role is UserRole.STUDENT:
        query = (
            select(Lesson)
            .join(LessonAssignment, LessonAssignment.lesson_id == Lesson.id)
            .where(
                LessonAssignment.student_id == actor.id,
                LessonAssignment.status != "cancelled",
                or_(
                    LessonAssignment.available_from.is_(None),
                    LessonAssignment.available_from <= datetime.now(UTC),
                ),
            )
            .distinct()
        )
    else:
        if actor.school_id is None:
            return []
        query = select(Lesson).where(Lesson.school_id == actor.school_id)
        if (scope or default_lesson_scope(actor)) is LessonScope.MINE:
            taught = (
                select(TeacherClassAssignment.class_id)
                .where(
                    TeacherClassAssignment.teacher_id == actor.id,
                    TeacherClassAssignment.removed_at.is_(None),
                )
                .scalar_subquery()
            )
            assigned = (
                select(LessonAssignment.lesson_id)
                .where(
                    LessonAssignment.status != "cancelled",
                    or_(
                        LessonAssignment.teacher_id == actor.id,
                        LessonAssignment.class_id.in_(taught),
                    ),
                )
                .scalar_subquery()
            )
            query = query.where(
                or_(
                    Lesson.created_by_user_id == actor.id,
                    Lesson.id.in_(assigned),
                )
            )
    query = query.order_by(Lesson.created_at.desc())
    if limit is not None:
        query = query.limit(limit)
    return list((await session.scalars(query)).all())


def default_lesson_scope(actor: User) -> LessonScope:
    """Teachers open on their own work; admins oversee the whole school."""
    return LessonScope.MINE if actor.role is UserRole.TEACHER else LessonScope.SCHOOL
