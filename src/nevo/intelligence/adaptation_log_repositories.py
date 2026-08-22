from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.account import Class, StudentClassEnrollment, User
from nevo.db.models.content import Lesson
from nevo.db.models.signal_event import LessonSession, SignalEvent
from nevo.intelligence.adaptation_log import (
    ADAPTATION_EVENT_TYPES,
    adaptation_plain_language,
    trigger_plain_language,
)
from nevo.intelligence.entities import AdaptationEventLogRecord


class SqlAlchemyAdaptationEventLogRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def events(
        self,
        *,
        school_id: UUID,
        class_id: UUID | None,
        student_id: UUID | None,
        lesson_id: UUID | None,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[AdaptationEventLogRecord, ...]:
        statement = (
            _base_query(
                school_id=school_id,
                class_id=class_id,
                student_id=student_id,
                lesson_id=lesson_id,
                date_from=date_from,
                date_to=date_to,
            )
            .order_by(SignalEvent.timestamp.desc(), SignalEvent.id.desc())
            .limit(limit)
            .offset(offset)
        )
        async with self._sessions() as session:
            rows = (await session.execute(statement)).all()
        return tuple(_record_from_row(row) for row in rows)

    async def count(
        self,
        *,
        school_id: UUID,
        class_id: UUID | None,
        student_id: UUID | None,
        lesson_id: UUID | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> int:
        statement = _base_query(
            school_id=school_id,
            class_id=class_id,
            student_id=student_id,
            lesson_id=lesson_id,
            date_from=date_from,
            date_to=date_to,
        ).with_only_columns(func.count(SignalEvent.id)).order_by(None)
        async with self._sessions() as session:
            return int(await session.scalar(statement) or 0)


def _base_query(
    *,
    school_id: UUID,
    class_id: UUID | None,
    student_id: UUID | None,
    lesson_id: UUID | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> Select[tuple[SignalEvent, User, Lesson]]:
    statement = (
        select(SignalEvent, User, Lesson)
        .join(User, User.id == SignalEvent.student_id)
        .join(LessonSession, LessonSession.id == SignalEvent.session_id)
        .join(Lesson, Lesson.id == LessonSession.lesson_id)
        .where(
            User.school_id == school_id,
            SignalEvent.event_type.in_(ADAPTATION_EVENT_TYPES),
        )
    )
    if class_id is not None:
        statement = statement.join(
            StudentClassEnrollment,
            StudentClassEnrollment.student_id == User.id,
        ).join(Class, Class.id == StudentClassEnrollment.class_id)
        statement = statement.where(
            StudentClassEnrollment.class_id == class_id,
            Class.school_id == school_id,
        )
    if student_id is not None:
        statement = statement.where(SignalEvent.student_id == student_id)
    if lesson_id is not None:
        statement = statement.where(LessonSession.lesson_id == lesson_id)
    if date_from is not None:
        statement = statement.where(SignalEvent.timestamp >= date_from)
    if date_to is not None:
        statement = statement.where(SignalEvent.timestamp <= date_to)
    return statement


def _record_from_row(row) -> AdaptationEventLogRecord:
    event, student, lesson = row
    event_data = event.event_data or {}
    return AdaptationEventLogRecord(
        id=event.id,
        student_id=student.id,
        student_first_name=student.first_name or "Student",
        lesson_id=lesson.id,
        lesson_title=lesson.title,
        timestamp=event.timestamp,
        trigger=trigger_plain_language(event.event_type, event_data),
        adaptation=adaptation_plain_language(event.event_type, event_data),
        event_type=event.event_type.value,
    )
