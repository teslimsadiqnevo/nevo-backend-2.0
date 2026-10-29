from collections.abc import Iterable
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.api.request_context import current_request
from nevo.auth.entities import AuthPrincipal
from nevo.db.models.account import Class, StudentClassEnrollment, User
from nevo.db.models.teacher_assignment import TeacherClassAssignment
from nevo.db.models.permission import Admin, AdminScopeAssignment
from nevo.domain.permissions.vocabulary import PermissionScope

#: What an administrator may reach before confirming their address. Reading
#: the console is deliberate - a school owner who registers at night and
#: cannot find the email abandons entirely if the door is shut - and so is the
#: confirmation flow itself, which is the way out of this state.
UNCONFIRMED_WRITE_ALLOWLIST = (
    "/api/v1/admin/email-confirmation",
    "/api/v1/admin/email",
    "/api/v1/auth",
)

ADMIN_ROLES = {"senco_admin", "other_admin"}


async def actor_user(session: AsyncSession, principal: AuthPrincipal) -> User:
    user = await session.get(User, principal.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account unavailable")
    _refuse_unconfirmed_write(user)
    return user


def _refuse_unconfirmed_write(user: User) -> None:
    """An administrator who has not proved their address writes nothing.

    Here rather than on each handler because the rule covers every write in
    the product - imports, class creation, invitations, consent requests - and
    a rule enforced per handler is a rule the next handler forgets. The
    request's method reaches this function through a context variable, since
    this is a funnel for a principal and a session rather than a request.
    """

    if user.email_confirmed_at is not None or user.role.value not in ADMIN_ROLES:
        return
    request = current_request()
    if request is None or not request.writes:
        return
    if request.path.startswith(UNCONFIRMED_WRITE_ALLOWLIST):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "email_not_confirmed",
            "message": (
                "Confirm your email address before making changes. We sent a "
                "link to "
                f"{user.email}; you can send it again from the banner at the "
                "top of the console."
            ),
            "email": user.email,
        },
    )


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


async def require_teacher_console_actor(session: AsyncSession, principal: AuthPrincipal) -> User:
    actor = await require_school_actor(session, principal)
    if actor.role.value == "teacher":
        return actor
    if actor.role.value not in ADMIN_ROLES:
        raise HTTPException(403, detail={"code": "teacher_scope_required"})
    assigned = await session.scalar(
        select(AdminScopeAssignment.id)
        .join(Admin, Admin.id == AdminScopeAssignment.admin_id)
        .where(
            Admin.user_id == actor.id,
            Admin.school_id == actor.school_id,
            AdminScopeAssignment.scope == PermissionScope.TEACHER,
            AdminScopeAssignment.revoked_at.is_(None),
        ).limit(1)
    )
    if assigned is None:
        raise HTTPException(403, detail={"code": "teacher_scope_required"})
    return actor


async def can_be_class_teacher(session: AsyncSession, user: User) -> bool:
    if user.role.value == "teacher":
        return True
    if user.role.value not in ADMIN_ROLES or user.status.value != "active":
        return False
    return bool(await session.scalar(
        select(AdminScopeAssignment.id)
        .join(Admin, Admin.id == AdminScopeAssignment.admin_id)
        .where(Admin.user_id == user.id,
               Admin.school_id == user.school_id,
               AdminScopeAssignment.scope == PermissionScope.TEACHER,
               AdminScopeAssignment.revoked_at.is_(None)).limit(1)
    ))


async def require_teacher_console_class(session: AsyncSession, actor: User, class_id: UUID) -> None:
    assigned = await session.scalar(select(TeacherClassAssignment.id).where(
        TeacherClassAssignment.class_id == class_id,
        TeacherClassAssignment.teacher_id == actor.id,
        TeacherClassAssignment.school_id == actor.school_id,
        TeacherClassAssignment.removed_at.is_(None),
    ).limit(1))
    if assigned is None:
        raise HTTPException(404, detail={"code": "class_not_assigned"})


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
    from nevo.api.learning_support import holds_learning_support

    if await holds_learning_support(session, actor):
        return True
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


async def require_approved_lessons(
    session: AsyncSession,
    lesson_ids: Iterable[UUID],
) -> None:
    """Refuse to put a lesson in front of children before a teacher clears it.

    SCRUM-37: approval is manual and deliberate, and the teacher stays in
    control of what reaches students. Assignment is the moment that control is
    exercised or lost, and there are two routes to it - one lesson at a time
    and several at once - so the check lives here rather than in either of
    them. A gate on one door is not a gate.

    The current lesson-wide sign-offs are mandatory. Per-section approvals
    remain visible for review, but cannot substitute for the professional
    decision over the complete lesson.
    """

    from sqlalchemy import func

    from nevo.api.lesson_review import outstanding_key_points
    from nevo.db.models.content import Lesson, LessonSegment

    wanted = list(dict.fromkeys(lesson_ids))
    if not wanted:
        return
    section_rows = (
        await session.execute(
            select(Lesson.id, Lesson.title, func.count(LessonSegment.id))
            .join(LessonSegment, LessonSegment.lesson_id == Lesson.id)
            .where(
                Lesson.id.in_(wanted),
                LessonSegment.needs_review.is_(True),
                LessonSegment.approved_at.is_(None),
            )
            .group_by(Lesson.id, Lesson.title)
        )
    ).all()
    unsettled = await outstanding_key_points(session, wanted)
    titles = {lesson_id: title for lesson_id, title, _ in section_rows}
    section_counts = {lesson_id: int(count) for lesson_id, _, count in section_rows}
    from nevo.api.lesson_review import _review_result

    lessons = await session.scalars(select(Lesson).where(Lesson.id.in_(wanted)))
    for lesson in lessons:
        review = await _review_result(session, lesson)
        if not review.review_complete:
            section_counts[lesson.id] = max(1, section_counts.get(lesson.id, 0))
        else:
            section_counts.pop(lesson.id, None)
    if unsettled:
        missing = [key for key in unsettled if key not in titles]
        if missing:
            named = await session.execute(
                select(Lesson.id, Lesson.title).where(Lesson.id.in_(missing))
            )
            titles.update({row[0]: row[1] for row in named.all()})
    segments_left = section_counts
    outstanding = sorted(set(segments_left) | set(unsettled), key=lambda key: str(titles.get(key)))
    if not outstanding:
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "lesson_not_approved",
            # The refusal names what is outstanding, because a teacher who is
            # told only "not ready" has nowhere to go: LR-07.
            "message": "; ".join(
                _outstanding_phrase(
                    str(titles.get(lesson_id) or "This lesson"),
                    segments=segments_left.get(lesson_id, 0),
                    key_points=unsettled.get(lesson_id, 0),
                )
                for lesson_id in outstanding
            ),
            "lessons": [
                {
                    "lessonId": str(lesson_id),
                    "unapprovedSegmentCount": segments_left.get(lesson_id, 0),
                    "outstandingKeyPointCount": unsettled.get(lesson_id, 0),
                }
                for lesson_id in outstanding
            ],
        },
    )


def _outstanding_phrase(title: str, *, segments: int, key_points: int) -> str:
    parts = []
    if key_points:
        parts.append(f"{key_points} key point{'s' if key_points != 1 else ''} to check")
    if segments:
        parts.append(f"{segments} segment{'s' if segments != 1 else ''} to approve")
    return f"{title}: {' and '.join(parts)}"
