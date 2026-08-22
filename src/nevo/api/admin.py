from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from nevo.api.permissions import RequireScope
from nevo.domain.permissions.vocabulary import PermissionScope
from nevo.intelligence.adaptation_log import AdaptationEventLogService
from nevo.intelligence.entities import AdaptationEventLogRecord
from nevo.permissions.entities import PermissionSnapshot

router = APIRouter(prefix="/api/admin", tags=["admin"])


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
            student_id=record.student_id,
            student_first_name=record.student_first_name,
            lesson_id=record.lesson_id,
            lesson_title=record.lesson_title,
            timestamp=record.timestamp,
            trigger=record.trigger,
            adaptation=record.adaptation,
            event_type=record.event_type,
        )


class AdaptationEventLogResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    events: list[AdaptationEventLogRow]
    total: int
    limit: int
    offset: int


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


AdaptationEventLogDependency = Annotated[
    AdaptationEventLogService,
    Depends(get_adaptation_event_log_service),
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
