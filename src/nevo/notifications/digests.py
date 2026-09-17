"""The weekly attention summary a teacher gets whether or not they log in.

Attention flags were raised, stored and shown on a screen. A teacher who did
not open that screen never learned a child had been flagged, and the
notification type that existed to tell them was never once raised.

Weekly rather than per flag, by ruling: a flag is a pattern noticed over days,
and a message for each one trains a teacher to ignore the lot.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.account import Class, StudentClassEnrollment, User
from nevo.db.models.attention_flag import AttentionFlag
from nevo.db.models.signal_event import SignalEvent
from nevo.db.models.teacher_assignment import TeacherClassAssignment
from nevo.domain.accounts.vocabulary import NotificationType, UserRole, UserStatus
from nevo.domain.signal_events.vocabulary import SignalEventType
from nevo.notifications.dispatch import notify

logger = logging.getLogger(__name__)

DIGEST_WINDOW = timedelta(days=7)


async def send_attention_digests(
    sessions: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
) -> str:
    """One message per teacher who has unacknowledged flags on their classes."""

    moment = now or datetime.now(UTC)
    since = moment - DIGEST_WINDOW
    sent = 0
    async with sessions.begin() as session:
        for teacher_id, role, children, flags in await _teachers_with_flags(session, since):
            await notify(
                session,
                recipient_id=teacher_id,
                recipient_role=role,
                notification_type=NotificationType.ATTENTION_SUMMARY,
                title=(f"{children} learner{'s' if children != 1 else ''} to look at this week"),
                description=(
                    f"{flags} attention flag{'s' if flags != 1 else ''} across "
                    f"{children} learner{'s' if children != 1 else ''} in your classes "
                    "have not been marked as seen."
                ),
                navigates_to="/teacher/learning-support",
            )
            sent += 1
    return f"sent {sent} attention digest(s)"


async def _teachers_with_flags(
    session: AsyncSession,
    since: datetime,
) -> list[tuple[object, str, int, int]]:
    """Teachers, and what is waiting on their classes.

    Counted by child as well as by flag, because the number a teacher acts on
    is how many learners need them - one child with four flags is one
    conversation, not four.
    """

    rows = (
        await session.execute(
            select(
                User.id,
                User.role,
                func.count(func.distinct(AttentionFlag.student_id)),
                func.count(AttentionFlag.id),
            )
            .select_from(TeacherClassAssignment)
            .join(User, User.id == TeacherClassAssignment.teacher_id)
            .join(Class, Class.id == TeacherClassAssignment.class_id)
            .join(
                StudentClassEnrollment,
                StudentClassEnrollment.class_id == Class.id,
            )
            .join(
                AttentionFlag,
                AttentionFlag.student_id == StudentClassEnrollment.student_id,
            )
            .where(
                TeacherClassAssignment.removed_at.is_(None),
                Class.archived_at.is_(None),
                User.status == UserStatus.ACTIVE,
                User.role == UserRole.TEACHER,
                AttentionFlag.acknowledged_at.is_(None),
                AttentionFlag.generated_at >= since,
            )
            .group_by(User.id, User.role)
        )
    ).all()
    return [(row[0], row[1], int(row[2]), int(row[3])) for row in rows]


async def notify_modality_shifts(
    session: AsyncSession,
    *,
    lesson_session_id: UUID,
    student_id: UUID,
) -> int:
    """Tell a child's teachers when Nevo changed how a lesson was delivered.

    Raised after the lesson rather than during it. A teacher is not watching a
    dashboard while they teach, and a message that arrives mid-lesson is an
    interruption about something already handled - what they need is to know
    it happened, before they plan the next one.

    Silent when nothing shifted, so the notification means something when it
    does arrive.
    """

    shifts = int(
        await session.scalar(
            select(func.count(SignalEvent.id)).where(
                SignalEvent.session_id == lesson_session_id,
                SignalEvent.event_type.in_(
                    {
                        SignalEventType.MODALITY_SUGGESTION_ACCEPTED,
                        SignalEventType.MODALITY_MANUAL_SWITCH,
                    }
                ),
            )
        )
        or 0
    )
    if not shifts:
        return 0

    student = await session.get(User, student_id)
    child = (student.first_name if student else None) or "A learner"
    teachers = (
        await session.scalars(
            select(User)
            .select_from(TeacherClassAssignment)
            .join(User, User.id == TeacherClassAssignment.teacher_id)
            .join(
                StudentClassEnrollment,
                StudentClassEnrollment.class_id == TeacherClassAssignment.class_id,
            )
            .where(
                StudentClassEnrollment.student_id == student_id,
                TeacherClassAssignment.removed_at.is_(None),
                User.status == UserStatus.ACTIVE,
            )
            .distinct()
        )
    ).all()
    for teacher in teachers:
        await notify(
            session,
            recipient_id=teacher.id,
            recipient_role=teacher.role,
            notification_type=NotificationType.MODALITY_SHIFT,
            title=f"{child} switched how they were learning",
            description=(
                f"Nevo changed delivery {shifts} time{'s' if shifts != 1 else ''} "
                f"during {child}'s last lesson. Worth a look before the next one."
            ),
            navigates_to="/teacher/adaptation-insights",
        )
    return len(teachers)
