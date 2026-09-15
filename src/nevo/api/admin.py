from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from nevo.api.permissions import RequireScope
from nevo.domain.permissions.vocabulary import PermissionScope
from nevo.domain.signal_events.vocabulary import SignalEventType
from nevo.intelligence.adaptation_log import (
    ADAPTATION_EVENT_TYPES,
    AdaptationEventLogService,
)
from nevo.intelligence.compliance_audit import (
    ComplianceFinding,
    NdpaComplianceAudit,
    NdpaComplianceAuditService,
)
from nevo.intelligence.entities import AdaptationEventLogRecord
from nevo.permissions.entities import PermissionSnapshot

router = APIRouter(prefix="/api/admin", tags=["admin"])


class AdaptationEventType(StrEnum):
    """The kinds of adaptation this log holds, and the only filter values.

    Spelled out rather than generated from the event set so the schema shows
    a client what it may ask for. The assertion below keeps the two from
    drifting apart: a new adaptation signal that is not listed here is a
    filter value nobody can discover.
    """

    SIMPLIFY_TRIGGER = "simplify_trigger"
    EXPAND_TRIGGER = "expand_trigger"
    SLOWER_TRIGGER = "slower_trigger"
    BREAK_SUGGESTED = "break_suggested"
    MODALITY_SUGGESTION_SHOWN = "modality_suggestion_shown"
    MODALITY_SUGGESTION_ACCEPTED = "modality_suggestion_accepted"
    MODALITY_SWITCH_OUTCOME = "modality_switch_outcome"
    MODALITY_MANUAL_SWITCH = "modality_manual_switch"


assert {item.value for item in AdaptationEventType} == {
    item.value for item in ADAPTATION_EVENT_TYPES
}, "AdaptationEventType has drifted from the adaptation signals the log reads"


class AdaptationEventLogRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    student_id: UUID = Field(alias="studentId")
    student_first_name: str = Field(alias="studentFirstName")
    lesson_id: UUID = Field(alias="lessonId")
    lesson_title: str = Field(alias="lessonTitle")
    timestamp: datetime
    trigger: str
    adaptation: str
    event_type: str = Field(alias="eventType")

    @classmethod
    def from_record(cls, record: AdaptationEventLogRecord) -> "AdaptationEventLogRow":
        return cls(
            id=record.id,
            studentId=record.student_id,
            studentFirstName=record.student_first_name,
            lessonId=record.lesson_id,
            lessonTitle=record.lesson_title,
            timestamp=record.timestamp,
            trigger=record.trigger,
            adaptation=record.adaptation,
            eventType=record.event_type,
        )


class AdaptationEventLogResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    events: list[AdaptationEventLogRow]
    total: int
    limit: int
    offset: int


class ComplianceFindingResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    table: str
    record_id: UUID = Field(alias="recordId")
    field: str
    term: str

    @classmethod
    def from_record(cls, finding: ComplianceFinding) -> "ComplianceFindingResponse":
        return cls(
            table=finding.table,
            recordId=finding.record_id,
            field=finding.field,
            term=finding.term,
        )


class NdpaComplianceAuditResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    school_id: UUID = Field(alias="schoolId")
    school_name: str = Field(alias="schoolName")
    generated_at: datetime = Field(alias="generatedAt")
    students_profiled: int = Field(alias="studentsProfiled")
    adaptation_events_logged: int = Field(alias="adaptationEventsLogged")
    diagnostic_labels_stored: int = Field(alias="diagnosticLabelsStored")
    compliant: bool
    findings: list[ComplianceFindingResponse]

    @classmethod
    def from_audit(cls, audit: NdpaComplianceAudit) -> "NdpaComplianceAuditResponse":
        return cls(
            schoolId=audit.school_id,
            schoolName=audit.school_name,
            generatedAt=audit.generated_at,
            studentsProfiled=audit.students_profiled,
            adaptationEventsLogged=audit.adaptation_events_logged,
            diagnosticLabelsStored=audit.diagnostic_labels_stored,
            compliant=audit.compliant,
            findings=[ComplianceFindingResponse.from_record(finding) for finding in audit.findings],
        )


def get_adaptation_event_log_service(request: Request) -> AdaptationEventLogService:
    service = getattr(request.app.state, "adaptation_event_log_service", None)
    if not isinstance(service, AdaptationEventLogService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_unavailable",
                "message": "Adaptation event log is temporarily unavailable.",
            },
        )
    return service


def get_ndpa_compliance_audit_service(request: Request) -> NdpaComplianceAuditService:
    service = getattr(request.app.state, "ndpa_compliance_audit_service", None)
    if not isinstance(service, NdpaComplianceAuditService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_unavailable",
                "message": "NDPA compliance audit is temporarily unavailable.",
            },
        )
    return service


AdaptationEventLogDependency = Annotated[
    AdaptationEventLogService,
    Depends(get_adaptation_event_log_service),
]
NdpaComplianceAuditDependency = Annotated[
    NdpaComplianceAuditService,
    Depends(get_ndpa_compliance_audit_service),
]
AdminOversightDependency = Annotated[
    PermissionSnapshot,
    Depends(RequireScope(PermissionScope.OVERSIGHT)),
]


@router.get("/adaptation-log", response_model=AdaptationEventLogResponse)
async def adaptation_log(
    actor: AdminOversightDependency,
    service: AdaptationEventLogDependency,
    class_id: Annotated[UUID | None, Query(alias="classId")] = None,
    student_id: Annotated[UUID | None, Query(alias="studentId")] = None,
    lesson_id: Annotated[UUID | None, Query(alias="lessonId")] = None,
    event_type: Annotated[
        list[AdaptationEventType] | None,
        Query(
            alias="eventType",
            description=(
                "Show only these kinds of adaptation. Repeat the parameter to "
                "pass more than one; omit it for all of them."
            ),
        ),
    ] = None,
    date_from: Annotated[datetime | None, Query(alias="dateFrom")] = None,
    date_to: Annotated[datetime | None, Query(alias="dateTo")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdaptationEventLogResponse:
    if actor.school_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "school_context_required",
                "message": "A school admin context is required.",
            },
        )
    records, total = await service.events(
        school_id=actor.school_id,
        class_id=class_id,
        student_id=student_id,
        lesson_id=lesson_id,
        event_types=(
            frozenset(SignalEventType(item.value) for item in event_type) if event_type else None
        ),
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return AdaptationEventLogResponse(
        events=[AdaptationEventLogRow.from_record(record) for record in records],
        total=total,
        limit=min(max(limit, 1), 100),
        offset=max(offset, 0),
    )


@router.get("/compliance-audit", response_model=NdpaComplianceAuditResponse)
async def compliance_audit_summary(
    actor: AdminOversightDependency,
    service: NdpaComplianceAuditDependency,
) -> NdpaComplianceAuditResponse:
    school_id = _school_id_or_403(actor)
    return NdpaComplianceAuditResponse.from_audit(await service.summary(school_id=school_id))


@router.post("/compliance-audit/scan", response_model=NdpaComplianceAuditResponse)
async def run_compliance_audit_scan(
    actor: AdminOversightDependency,
    service: NdpaComplianceAuditDependency,
) -> NdpaComplianceAuditResponse:
    school_id = _school_id_or_403(actor)
    return NdpaComplianceAuditResponse.from_audit(await service.scan(school_id=school_id))


@router.get("/compliance-audit/report.pdf")
async def compliance_audit_report_pdf(
    actor: AdminOversightDependency,
    service: NdpaComplianceAuditDependency,
) -> Response:
    school_id = _school_id_or_403(actor)
    return Response(
        content=await service.report_pdf(school_id=school_id),
        media_type="application/pdf",
        headers={"Content-Disposition": ('attachment; filename="nevo-ndpa-compliance-report.pdf"')},
    )


def _school_id_or_403(actor: PermissionSnapshot) -> UUID:
    if actor.school_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "school_context_required",
                "message": "A school admin context is required.",
            },
        )
    return actor.school_id
