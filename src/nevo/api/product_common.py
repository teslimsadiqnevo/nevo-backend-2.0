from collections.abc import Iterable
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.auth.entities import AuthPrincipal
from nevo.db.models.account import Class, StudentClassEnrollment, User
from nevo.db.models.teacher_assignment import TeacherClassAssignment


async def actor_user(session: AsyncSession, principal: AuthPrincipal) -> User:
    user = await session.get(User, principal.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account unavailable")
    return user


async def require_school_actor(
    session: AsyncSession,
    principal: AuthPrincipal,
    *,
    roles: Iterable[str] | None = None,
) -> User:
    user = await actor_user(session, principal)
    if user.school_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="School context required")
    allowed = set(roles or ())
    if allowed and user.role.value not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Role is not permitted")
    return user


async def require_school_resource(
    session: AsyncSession,
    principal: AuthPrincipal,
    resource_school_id: UUID | None,
) -> User:
    user = await require_school_actor(session, principal)
    if resource_school_id is not None and user.school_id != resource_school_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    return user


async def can_access_student(
    session: AsyncSession,
    actor: User,
    student_id: UUID,
) -> bool:
    if actor.id == student_id:
        return True
    student = await session.get(User, student_id)
    if student is None or student.school_id != actor.school_id:
        return False
    if actor.role.value in {"senco_admin", "other_admin"}:
        return True
    if actor.role.value != "teacher":
        return False
    return bool(
        await session.scalar(
            select(TeacherClassAssignment.id)
            .join(
                StudentClassEnrollment,
                StudentClassEnrollment.class_id == TeacherClassAssignment.class_id,
            )
            .where(
                StudentClassEnrollment.student_id == student_id,
                TeacherClassAssignment.teacher_id == actor.id,
                TeacherClassAssignment.removed_at.is_(None),
            )
            .limit(1)
        )
    )


async def require_student_access(
    session: AsyncSession,
    principal: AuthPrincipal,
    student_id: UUID,
) -> User:
    actor = await actor_user(session, principal)
    if not await can_access_student(session, actor, student_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    return actor


async def require_class_access(
    session: AsyncSession,
    principal: AuthPrincipal | User,
    class_id: UUID,
) -> Class:
    actor = (
        principal if isinstance(principal, User) else await require_school_actor(session, principal)
    )
    school_class = await session.get(Class, class_id)
    if school_class is None or school_class.school_id != actor.school_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Class not found")
    if actor.role.value == "teacher":
        assignment = await session.scalar(
            select(TeacherClassAssignment.id).where(
                TeacherClassAssignment.class_id == class_id,
                TeacherClassAssignment.teacher_id == actor.id,
                TeacherClassAssignment.removed_at.is_(None),
            )
        )
        if assignment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Class not found")
    return school_class
