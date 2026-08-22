from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.account import School, User
from nevo.db.models.ask_nevo import AskNevoInteraction
from nevo.db.models.attention_flag import (
    AttentionFlag,
    Escalation,
    InterventionRecommendation,
)
from nevo.db.models.export import IepExport, StudentRecordEvent
from nevo.db.models.learner_profile import (
    LearnerProfile,
    LearnerProfileAttentionFlag,
    LearnerProfileHistory,
)
from nevo.db.models.signal_event import SignalEvent
from nevo.intelligence.adaptation_log import ADAPTATION_EVENT_TYPES
from nevo.intelligence.compliance_audit import ComplianceSummary, ScannableRecord


class SqlAlchemyNdpaComplianceAuditRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def summary(self, *, school_id: UUID) -> ComplianceSummary:
        async with self._sessions() as session:
            school_name = await session.scalar(
                select(School.name).where(School.id == school_id)
            )
            students_profiled = int(
                await session.scalar(
                    select(func.count(LearnerProfile.id))
                    .join(User, User.id == LearnerProfile.learner_id)
                    .where(User.school_id == school_id)
                )
                or 0
            )
            adaptation_events_logged = int(
                await session.scalar(
                    select(func.count(SignalEvent.id))
                    .join(User, User.id == SignalEvent.student_id)
                    .where(
                        User.school_id == school_id,
                        SignalEvent.event_type.in_(ADAPTATION_EVENT_TYPES),
                    )
                )
                or 0
            )
        return ComplianceSummary(
            school_id=school_id,
            school_name=school_name or "School",
            students_profiled=students_profiled,
            adaptation_events_logged=adaptation_events_logged,
        )

    async def scannable_records(
        self,
        *,
        school_id: UUID,
    ) -> tuple[ScannableRecord, ...]:
        async with self._sessions() as session:
            records: list[ScannableRecord] = []
            records.extend(
                await _student_scoped_records(
                    session,
                    school_id=school_id,
                    model=LearnerProfileHistory,
                    fields=("change_reason",),
                )
            )
            records.extend(
                await _student_scoped_records(
                    session,
                    school_id=school_id,
                    model=LearnerProfileAttentionFlag,
                    fields=("dimension", "current_value", "recommended_value", "rationale"),
                )
            )
            records.extend(
                await _student_scoped_records(
                    session,
                    school_id=school_id,
                    model=AttentionFlag,
                    fields=("description",),
                )
            )
            records.extend(
                await _student_scoped_records(
                    session,
                    school_id=school_id,
                    model=Escalation,
                    fields=("teacher_note",),
                )
            )
            records.extend(
                await _student_scoped_records(
                    session,
                    school_id=school_id,
                    model=InterventionRecommendation,
                    fields=("recommendation_text",),
                )
            )
            records.extend(
                await _student_scoped_records(
                    session,
                    school_id=school_id,
                    model=IepExport,
                    fields=("export_content", "source_summary", "annotations", "review_note"),
                )
            )
            records.extend(
                await _student_scoped_records(
                    session,
                    school_id=school_id,
                    model=StudentRecordEvent,
                    fields=("payload",),
                )
            )
            records.extend(
                await _student_scoped_records(
                    session,
                    school_id=school_id,
                    model=SignalEvent,
                    fields=("event_data",),
                )
            )
            records.extend(
                await _actor_scoped_records(
                    session,
                    school_id=school_id,
                    model=AskNevoInteraction,
                    fields=("current_page", "context_ids"),
                )
            )
        return tuple(records)


async def _student_scoped_records(
    session: AsyncSession,
    *,
    school_id: UUID,
    model: type[Any],
    fields: tuple[str, ...],
) -> tuple[ScannableRecord, ...]:
    user_id_column = model.student_id if hasattr(model, "student_id") else model.learner_id
    rows = (
        await session.execute(
            select(model)
            .join(User, User.id == user_id_column)
            .where(User.school_id == school_id)
        )
    ).scalars()
    return _records_from_rows(model.__tablename__, rows, fields)


async def _actor_scoped_records(
    session: AsyncSession,
    *,
    school_id: UUID,
    model: type[Any],
    fields: tuple[str, ...],
) -> tuple[ScannableRecord, ...]:
    rows = (
        await session.execute(
            select(model)
            .join(User, User.id == model.actor_user_id)
            .where(User.school_id == school_id)
        )
    ).scalars()
    return _records_from_rows(model.__tablename__, rows, fields)


def _records_from_rows(
    table: str,
    rows: Iterable[Any],
    fields: tuple[str, ...],
) -> tuple[ScannableRecord, ...]:
    records: list[ScannableRecord] = []
    for row in rows:
        for field in fields:
            value = getattr(row, field, None)
            if value is not None:
                records.append(
                    ScannableRecord(
                        table=table,
                        record_id=row.id,
                        field=field,
                        value=value,
                    )
                )
    return tuple(records)
