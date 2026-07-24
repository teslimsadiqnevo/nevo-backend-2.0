from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from nevo.api.auth import PrincipalDependency
from nevo.domain.exports.vocabulary import IepExportShareStatus, IepExportStatus
from nevo.exports.entities import IepExportRecord, IepExportShareRecord
from nevo.exports.errors import (
    ExportAlreadyFinalError,
    ExportNotFoundError,
    ExportPermissionError,
    ExportReviewRequiredError,
    ExportShareRequiresFinalError,
    ExportWorkflowError,
    ParentShareTargetError,
)
from nevo.exports.service import IepExportService

router = APIRouter(prefix="/api/v1/exports", tags=["exports"])


class CreateIepExportRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    student_id: UUID = Field(alias="studentId")
    period_start: date = Field(alias="periodStart")
    period_end: date = Field(alias="periodEnd")

    @model_validator(mode="after")
    def validate_period(self) -> "CreateIepExportRequest":
        if self.period_end < self.period_start:
            raise ValueError("periodEnd must be on or after periodStart")
        return self


class UpdateIepExportRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    export_content: str | None = Field(
        default=None,
        alias="exportContent",
        min_length=1,
    )
    annotations: list[dict[str, object]] | None = None


class FinalizeIepExportRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    review_note: str | None = Field(default=None, alias="reviewNote", max_length=5_000)
    export_content: str | None = Field(
        default=None,
        alias="exportContent",
        min_length=1,
    )


class ShareIepExportRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    parent_id: UUID = Field(alias="parentId")


class IepExportResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    student_id: UUID = Field(alias="studentId")
    requested_by_user_id: UUID = Field(alias="requestedByUserId")
    period_start: date = Field(alias="periodStart")
    period_end: date = Field(alias="periodEnd")
    status: IepExportStatus
    export_content: str = Field(alias="exportContent")
    source_summary: dict[str, object] = Field(alias="sourceSummary")
    annotations: list[dict[str, object]]
    ai_gateway_call_id: UUID | None = Field(alias="aiGatewayCallId")
    reviewed_by_user_id: UUID | None = Field(alias="reviewedByUserId")
    reviewed_at: datetime | None = Field(alias="reviewedAt")
    review_note: str | None = Field(alias="reviewNote")

    @classmethod
    def from_record(cls, record: IepExportRecord) -> "IepExportResponse":
        return cls(
            id=record.id,
            student_id=record.student_id,
            requested_by_user_id=record.requested_by_user_id,
            period_start=record.period_start,
            period_end=record.period_end,
            status=record.status,
            export_content=record.export_content,
            source_summary=record.source_summary,
            annotations=list(record.annotations),
            ai_gateway_call_id=record.ai_gateway_call_id,
            reviewed_by_user_id=record.reviewed_by_user_id,
            reviewed_at=record.reviewed_at,
            review_note=record.review_note,
        )


class IepExportShareResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    export_id: UUID = Field(alias="exportId")
    student_id: UUID = Field(alias="studentId")
    parent_id: UUID = Field(alias="parentId")
    shared_by_user_id: UUID = Field(alias="sharedByUserId")
    status: IepExportShareStatus
    shared_at: datetime = Field(alias="sharedAt")

    @classmethod
    def from_record(
        cls,
        record: IepExportShareRecord,
    ) -> "IepExportShareResponse":
        return cls(
            id=record.id,
            export_id=record.export_id,
            student_id=record.student_id,
            parent_id=record.parent_id,
            shared_by_user_id=record.shared_by_user_id,
            status=record.status,
            shared_at=record.shared_at,
        )


def get_iep_export_service(request: Request) -> IepExportService:
    service = getattr(request.app.state, "iep_export_service", None)
    if not isinstance(service, IepExportService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_unavailable",
                "message": "Exports are temporarily unavailable.",
            },
        )
    return service


IepExportDependency = Annotated[IepExportService, Depends(get_iep_export_service)]


@router.post("/iep", response_model=IepExportResponse)
async def create_iep_export(
    payload: CreateIepExportRequest,
    principal: PrincipalDependency,
    service: IepExportDependency,
) -> IepExportResponse:
    try:
        record = await service.create_draft(
            student_id=payload.student_id,
            period_start=payload.period_start,
            period_end=payload.period_end,
            actor_user_id=principal.user_id,
            actor_role=principal.role,
        )
    except ExportWorkflowError as error:
        raise public_export_error(error) from error
    return IepExportResponse.from_record(record)


@router.get("/iep/{export_id}", response_model=IepExportResponse)
async def get_iep_export(
    export_id: UUID,
    principal: PrincipalDependency,
    service: IepExportDependency,
) -> IepExportResponse:
    try:
        record = await service.get_export(
            export_id=export_id,
            actor_role=principal.role,
        )
    except ExportWorkflowError as error:
        raise public_export_error(error) from error
    return IepExportResponse.from_record(record)


@router.patch("/iep/{export_id}", response_model=IepExportResponse)
async def update_iep_export(
    export_id: UUID,
    payload: UpdateIepExportRequest,
    principal: PrincipalDependency,
    service: IepExportDependency,
) -> IepExportResponse:
    try:
        record = await service.update_draft(
            export_id=export_id,
            actor_user_id=principal.user_id,
            actor_role=principal.role,
            export_content=payload.export_content,
            annotations=payload.annotations,
        )
    except ExportWorkflowError as error:
        raise public_export_error(error) from error
    return IepExportResponse.from_record(record)


@router.post("/iep/{export_id}/review", response_model=IepExportResponse)
async def review_iep_export(
    export_id: UUID,
    payload: FinalizeIepExportRequest,
    principal: PrincipalDependency,
    service: IepExportDependency,
) -> IepExportResponse:
    try:
        record = await service.finalize(
            export_id=export_id,
            senco_user_id=principal.user_id,
            actor_role=principal.role,
            review_note=payload.review_note,
            export_content=payload.export_content,
        )
    except ExportWorkflowError as error:
        raise public_export_error(error) from error
    return IepExportResponse.from_record(record)


@router.post("/iep/{export_id}/share", response_model=IepExportShareResponse)
async def share_iep_export(
    export_id: UUID,
    payload: ShareIepExportRequest,
    principal: PrincipalDependency,
    service: IepExportDependency,
) -> IepExportShareResponse:
    try:
        record = await service.share(
            export_id=export_id,
            parent_id=payload.parent_id,
            actor_user_id=principal.user_id,
            actor_role=principal.role,
        )
    except ExportWorkflowError as error:
        raise public_export_error(error) from error
    return IepExportShareResponse.from_record(record)


def public_export_error(error: ExportWorkflowError) -> HTTPException:
    status_code = status.HTTP_400_BAD_REQUEST
    if isinstance(error, ExportNotFoundError):
        status_code = status.HTTP_404_NOT_FOUND
    if isinstance(
        error,
        (
            ExportPermissionError,
            ExportReviewRequiredError,
            ParentShareTargetError,
        ),
    ):
        status_code = status.HTTP_403_FORBIDDEN
    if isinstance(
        error,
        (
            ExportAlreadyFinalError,
            ExportShareRequiresFinalError,
        ),
    ):
        status_code = status.HTTP_409_CONFLICT
    return HTTPException(
        status_code=status_code,
        detail={
            "code": error.code,
            "message": error.public_message,
        },
    )
