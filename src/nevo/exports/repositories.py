from datetime import UTC, date, datetime, time
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.account import User
from nevo.db.models.attention_flag import (
    AttentionFlag,
    Escalation,
    InterventionRecommendation,
)
from nevo.db.models.consent import ParentLink
from nevo.db.models.export import IepExport, IepExportShare, StudentRecordEvent
from nevo.db.models.learner_profile import LearnerProfileHistory
from nevo.db.models.signal_event import SignalEvent
from nevo.domain.accounts.vocabulary import UserRole, UserStatus
from nevo.domain.exports.vocabulary import (
    IepExportShareStatus,
    IepExportStatus,
    StudentRecordEventType,
)
from nevo.exports.entities import ExportEvidence, IepExportRecord, IepExportShareRecord
from nevo.exports.errors import ExportNotFoundError, ParentShareTargetError


class SqlAlchemyIepExportRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def build_evidence(
        self,
        *,
        student_id: UUID,
        period_start: date,
        period_end: date,
    ) -> ExportEvidence:
        start_at, end_at = _date_bounds(period_start, period_end)
        async with self._sessions() as session:
            student = await session.scalar(
                select(User).where(
                    User.id == student_id,
                    User.role == UserRole.STUDENT,
                    User.status != UserStatus.DEACTIVATED,
                )
            )
            if student is None:
                raise ExportNotFoundError
            history = (
                await session.scalars(
                    select(LearnerProfileHistory)
                    .where(
                        LearnerProfileHistory.learner_id == student_id,
                        LearnerProfileHistory.created_at >= start_at,
                        LearnerProfileHistory.created_at <= end_at,
                    )
                    .order_by(LearnerProfileHistory.created_at)
                )
            ).all()
            flags = (
                await session.scalars(
                    select(AttentionFlag)
                    .where(
                        AttentionFlag.student_id == student_id,
                        AttentionFlag.generated_at >= start_at,
                        AttentionFlag.generated_at <= end_at,
                    )
                    .order_by(AttentionFlag.generated_at)
                )
            ).all()
            escalations = (
                await session.scalars(
                    select(Escalation)
                    .where(
                        Escalation.student_id == student_id,
                        Escalation.generated_at >= start_at,
                        Escalation.generated_at <= end_at,
                    )
                    .order_by(Escalation.generated_at)
                )
            ).all()
            recommendations = (
                await session.scalars(
                    select(InterventionRecommendation)
                    .where(
                        InterventionRecommendation.student_id == student_id,
                        InterventionRecommendation.generated_at >= start_at,
                        InterventionRecommendation.generated_at <= end_at,
                    )
                    .order_by(InterventionRecommendation.generated_at)
                )
            ).all()
            signal_counts = (
                await session.execute(
                    select(SignalEvent.event_type, func.count(SignalEvent.id))
                    .where(
                        SignalEvent.student_id == student_id,
                        SignalEvent.timestamp >= start_at,
                        SignalEvent.timestamp <= end_at,
                    )
                    .group_by(SignalEvent.event_type)
                )
            ).all()
        student_name = " ".join(
            part
            for part in (student.first_name, student.last_name)
            if part
        ) or "this learner"
        return ExportEvidence(
            student_name=student_name,
            payload={
                "student": {
                    "id": str(student.id),
                    "name": student_name,
                },
                "period": {
                    "start": period_start.isoformat(),
                    "end": period_end.isoformat(),
                },
                "profileDimensionHistory": [
                    _profile_history_payload(item) for item in history
                ],
                "signalTrends": [
                    {"eventType": event_type.value, "count": count}
                    for event_type, count in signal_counts
                ],
                "attentionFlags": [
                    {
                        "flagType": flag.flag_type.value,
                        "description": flag.description,
                        "generatedAt": flag.generated_at.isoformat(),
                        "acknowledged": flag.acknowledged_at is not None,
                    }
                    for flag in flags
                ],
                "escalations": [
                    {
                        "teacherId": str(item.teacher_id),
                        "teacherNote": item.teacher_note,
                        "generatedAt": item.generated_at.isoformat(),
                        "acknowledged": item.acknowledged_at is not None,
                    }
                    for item in escalations
                ],
                "interventionRecommendations": [
                    {
                        "attentionFlagId": str(item.attention_flag_id),
                        "recommendationText": item.recommendation_text,
                        "generatedAt": item.generated_at.isoformat(),
                    }
                    for item in recommendations
                ],
            },
        )

    async def create_export(
        self,
        *,
        student_id: UUID,
        requested_by_user_id: UUID,
        period_start: date,
        period_end: date,
        export_content: str,
        source_summary: dict[str, object],
        ai_gateway_call_id: UUID | None,
    ) -> IepExportRecord:
        export_id = uuid4()
        async with self._sessions.begin() as session:
            record = IepExport(
                id=export_id,
                student_id=student_id,
                requested_by_user_id=requested_by_user_id,
                period_start=period_start,
                period_end=period_end,
                status=IepExportStatus.DRAFT,
                export_content=export_content,
                source_summary=source_summary,
                annotations=[],
                ai_gateway_call_id=ai_gateway_call_id,
            )
            session.add(record)
            session.add(
                StudentRecordEvent(
                    student_id=student_id,
                    export_id=export_id,
                    event_type=StudentRecordEventType.EXPORT_DRAFT_CREATED,
                    actor_user_id=requested_by_user_id,
                    payload={
                        "periodStart": period_start.isoformat(),
                        "periodEnd": period_end.isoformat(),
                    },
                )
            )
        return await self.get_export(export_id)

    async def get_export(self, export_id: UUID) -> IepExportRecord:
        async with self._sessions() as session:
            record = await session.get(IepExport, export_id)
        if record is None:
            raise ExportNotFoundError
        return _export_record(record)

    async def update_draft(
        self,
        *,
        export_id: UUID,
        actor_user_id: UUID,
        export_content: str | None,
        annotations: list[dict[str, object]] | None,
    ) -> IepExportRecord:
        values: dict[str, object] = {"updated_at": func.now()}
        if export_content is not None:
            values["export_content"] = export_content
        if annotations is not None:
            values["annotations"] = annotations
        async with self._sessions.begin() as session:
            record = await session.get(IepExport, export_id)
            if record is None:
                raise ExportNotFoundError
            await session.execute(
                update(IepExport)
                .where(IepExport.id == export_id)
                .values(**values)
            )
            session.add(
                StudentRecordEvent(
                    student_id=record.student_id,
                    export_id=export_id,
                    event_type=StudentRecordEventType.EXPORT_DRAFT_EDITED,
                    actor_user_id=actor_user_id,
                    payload={
                        "contentEdited": export_content is not None,
                        "annotationsEdited": annotations is not None,
                    },
                )
            )
        return await self.get_export(export_id)

    async def finalize(
        self,
        *,
        export_id: UUID,
        senco_user_id: UUID,
        review_note: str | None,
        export_content: str | None,
    ) -> IepExportRecord:
        async with self._sessions.begin() as session:
            record = await session.get(IepExport, export_id)
            if record is None:
                raise ExportNotFoundError
            values: dict[str, object] = {
                "status": IepExportStatus.FINAL,
                "reviewed_by_user_id": senco_user_id,
                "reviewed_at": func.now(),
                "review_note": review_note,
                "updated_at": func.now(),
            }
            if export_content is not None:
                values["export_content"] = export_content
            await session.execute(
                update(IepExport)
                .where(IepExport.id == export_id)
                .values(**values)
            )
            session.add(
                StudentRecordEvent(
                    student_id=record.student_id,
                    export_id=export_id,
                    event_type=StudentRecordEventType.EXPORT_FINALIZED,
                    actor_user_id=senco_user_id,
                    payload={"reviewNoteProvided": bool(review_note)},
                )
            )
        return await self.get_export(export_id)

    async def share(
        self,
        *,
        export_id: UUID,
        parent_id: UUID,
        shared_by_user_id: UUID,
    ) -> IepExportShareRecord:
        export = await self.get_export(export_id)
        async with self._sessions.begin() as session:
            linked_parent_id = await session.scalar(
                select(ParentLink.parent_id).where(
                    ParentLink.student_id == export.student_id,
                    ParentLink.parent_id == parent_id,
                    ParentLink.account_created.is_(True),
                )
            )
            if linked_parent_id is None:
                raise ParentShareTargetError
            share = IepExportShare(
                id=uuid4(),
                export_id=export_id,
                student_id=export.student_id,
                parent_id=parent_id,
                shared_by_user_id=shared_by_user_id,
                status=IepExportShareStatus.SHARED,
            )
            session.add(share)
            await session.flush()
            session.add(
                StudentRecordEvent(
                    student_id=export.student_id,
                    export_id=export_id,
                    event_type=StudentRecordEventType.EXPORT_SHARED,
                    actor_user_id=shared_by_user_id,
                    payload={"parentId": str(parent_id)},
                )
            )
        return IepExportShareRecord(
            id=share.id,
            export_id=share.export_id,
            student_id=share.student_id,
            parent_id=share.parent_id,
            shared_by_user_id=share.shared_by_user_id,
            status=share.status,
            shared_at=share.shared_at,
        )


def _profile_history_payload(item: LearnerProfileHistory) -> dict[str, object | None]:
    return {
        "version": item.version,
        "createdAt": item.created_at.isoformat(),
        "visualSpatialPreference": item.visual_spatial_preference.value
        if item.visual_spatial_preference
        else None,
        "auditoryPreference": item.auditory_preference.value
        if item.auditory_preference
        else None,
        "readingWritingPreference": item.reading_writing_preference.value
        if item.reading_writing_preference
        else None,
        "interactiveKinestheticPreference": (
            item.interactive_kinesthetic_preference.value
            if item.interactive_kinesthetic_preference
            else None
        ),
        "cognitiveLoadThreshold": item.cognitive_load_threshold,
        "processingSpeed": item.processing_speed,
        "workingMemoryCapacity": item.working_memory_capacity,
        "attentionSpan": item.attention_span,
        "performanceSensitivity": item.performance_sensitivity,
    }


def _export_record(record: IepExport) -> IepExportRecord:
    return IepExportRecord(
        id=record.id,
        student_id=record.student_id,
        requested_by_user_id=record.requested_by_user_id,
        period_start=record.period_start,
        period_end=record.period_end,
        status=record.status,
        export_content=record.export_content,
        source_summary=record.source_summary,
        annotations=tuple(record.annotations),
        ai_gateway_call_id=record.ai_gateway_call_id,
        reviewed_by_user_id=record.reviewed_by_user_id,
        reviewed_at=record.reviewed_at,
        review_note=record.review_note,
    )


def _date_bounds(period_start: date, period_end: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(period_start, time.min, tzinfo=UTC),
        datetime.combine(period_end, time.max, tzinfo=UTC),
    )
