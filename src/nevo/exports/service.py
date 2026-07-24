import json
from datetime import date
from typing import Protocol
from uuid import UUID

from nevo.ai_gateway.compliance import ZeroTagCompliancePolicy
from nevo.ai_gateway.entities import AiGenerationRequest
from nevo.ai_gateway.service import AiGatewayService
from nevo.domain.accounts.vocabulary import UserRole
from nevo.domain.ai_gateway.vocabulary import AiService
from nevo.domain.exports.vocabulary import IepExportStatus
from nevo.exports.entities import (
    ExportEvidence,
    IepExportRecord,
    IepExportShareRecord,
)
from nevo.exports.errors import (
    ExportAlreadyFinalError,
    ExportPermissionError,
    ExportReviewRequiredError,
    ExportShareRequiresFinalError,
)


class IepExportRepository(Protocol):
    async def build_evidence(
        self,
        *,
        student_id: UUID,
        period_start: date,
        period_end: date,
    ) -> ExportEvidence: ...

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
    ) -> IepExportRecord: ...

    async def get_export(self, export_id: UUID) -> IepExportRecord: ...

    async def update_draft(
        self,
        *,
        export_id: UUID,
        actor_user_id: UUID,
        export_content: str | None,
        annotations: list[dict[str, object]] | None,
    ) -> IepExportRecord: ...

    async def finalize(
        self,
        *,
        export_id: UUID,
        senco_user_id: UUID,
        review_note: str | None,
        export_content: str | None,
    ) -> IepExportRecord: ...

    async def share(
        self,
        *,
        export_id: UUID,
        parent_id: UUID,
        shared_by_user_id: UUID,
    ) -> IepExportShareRecord: ...


class IepExportService:
    def __init__(
        self,
        *,
        repository: IepExportRepository,
        gateway: AiGatewayService,
        compliance: ZeroTagCompliancePolicy,
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._compliance = compliance

    async def create_draft(
        self,
        *,
        student_id: UUID,
        period_start: date,
        period_end: date,
        actor_user_id: UUID,
        actor_role: str,
    ) -> IepExportRecord:
        self._require_staff(actor_role)
        evidence = await self._repository.build_evidence(
            student_id=student_id,
            period_start=period_start,
            period_end=period_end,
        )
        result = await self._gateway.generate(
            AiGenerationRequest(
                requester_user_id=actor_user_id,
                student_id=student_id,
                service=AiService.NARRATIVE,
                prompt_name="iep_export.draft",
                variables={
                    "student_name": evidence.student_name,
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                    "evidence_summary": json.dumps(
                        evidence.payload,
                        sort_keys=True,
                        default=str,
                    ),
                },
                max_output_tokens=2_400,
            )
        )
        content = result.text
        if not self._compliance.inspect(content).allowed:
            content = self._compliance.sanitize(content)
        return await self._repository.create_export(
            student_id=student_id,
            requested_by_user_id=actor_user_id,
            period_start=period_start,
            period_end=period_end,
            export_content=content,
            source_summary=evidence.payload,
            ai_gateway_call_id=result.call_id,
        )

    async def get_export(self, *, export_id: UUID, actor_role: str) -> IepExportRecord:
        self._require_staff_or_parent(actor_role)
        return await self._repository.get_export(export_id)

    async def update_draft(
        self,
        *,
        export_id: UUID,
        actor_user_id: UUID,
        actor_role: str,
        export_content: str | None,
        annotations: list[dict[str, object]] | None,
    ) -> IepExportRecord:
        self._require_staff(actor_role)
        record = await self._repository.get_export(export_id)
        if record.status is IepExportStatus.FINAL:
            raise ExportAlreadyFinalError
        return await self._repository.update_draft(
            export_id=export_id,
            actor_user_id=actor_user_id,
            export_content=export_content,
            annotations=annotations,
        )

    async def finalize(
        self,
        *,
        export_id: UUID,
        senco_user_id: UUID,
        actor_role: str,
        review_note: str | None,
        export_content: str | None,
    ) -> IepExportRecord:
        if actor_role != UserRole.SENCO_ADMIN.value:
            raise ExportReviewRequiredError
        record = await self._repository.get_export(export_id)
        if record.status is IepExportStatus.FINAL:
            return record
        return await self._repository.finalize(
            export_id=export_id,
            senco_user_id=senco_user_id,
            review_note=review_note,
            export_content=export_content,
        )

    async def share(
        self,
        *,
        export_id: UUID,
        parent_id: UUID,
        actor_user_id: UUID,
        actor_role: str,
    ) -> IepExportShareRecord:
        self._require_staff(actor_role)
        record = await self._repository.get_export(export_id)
        if record.status is not IepExportStatus.FINAL:
            raise ExportShareRequiresFinalError
        return await self._repository.share(
            export_id=export_id,
            parent_id=parent_id,
            shared_by_user_id=actor_user_id,
        )

    def _require_staff(self, role: str) -> None:
        if role not in {
            UserRole.TEACHER.value,
            UserRole.SENCO_ADMIN.value,
            UserRole.OTHER_ADMIN.value,
        }:
            raise ExportPermissionError

    def _require_staff_or_parent(self, role: str) -> None:
        if role == UserRole.PARENT_GUARDIAN.value:
            return
        self._require_staff(role)
