from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import UUID

from nevo.domain.exports.vocabulary import IepExportShareStatus, IepExportStatus


@dataclass(frozen=True, slots=True)
class IepExportDraftRequest:
    student_id: UUID
    period_start: date
    period_end: date


@dataclass(frozen=True, slots=True)
class IepExportRecord:
    id: UUID
    student_id: UUID
    requested_by_user_id: UUID
    period_start: date
    period_end: date
    status: IepExportStatus
    export_content: str
    source_summary: dict[str, object]
    annotations: tuple[dict[str, object], ...]
    ai_gateway_call_id: UUID | None
    reviewed_by_user_id: UUID | None
    reviewed_at: datetime | None
    review_note: str | None


@dataclass(frozen=True, slots=True)
class IepExportShareRecord:
    id: UUID
    export_id: UUID
    student_id: UUID
    parent_id: UUID
    shared_by_user_id: UUID
    status: IepExportShareStatus
    shared_at: datetime


@dataclass(frozen=True, slots=True)
class ExportEvidence:
    student_name: str
    payload: dict[str, object] = field(default_factory=dict)
