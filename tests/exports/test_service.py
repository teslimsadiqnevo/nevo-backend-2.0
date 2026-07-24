from datetime import date, datetime
from uuid import uuid4

import pytest

from nevo.ai_gateway.entities import AiGenerationResult
from nevo.domain.ai_gateway.vocabulary import AiProviderName
from nevo.domain.exports.vocabulary import IepExportStatus
from nevo.exports.entities import ExportEvidence, IepExportRecord
from nevo.exports.errors import ExportReviewRequiredError, ExportShareRequiresFinalError
from nevo.exports.service import IepExportService


class FakeGateway:
    async def generate(self, request):
        return AiGenerationResult(
            text="## Progress\nThis learner benefits from short visual checks.",
            provider=AiProviderName.GEMINI,
            model="test",
            prompt_name=request.prompt_name,
            prompt_version=1,
            fallback_used=False,
            compliance_retries=0,
            call_id=uuid4(),
        )


class FakeCompliance:
    def inspect(self, text):
        return type("Compliance", (), {"allowed": True})()

    def sanitize(self, text):
        return text


class FakeRepository:
    def __init__(self) -> None:
        self.record = IepExportRecord(
            id=uuid4(),
            student_id=uuid4(),
            requested_by_user_id=uuid4(),
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            status=IepExportStatus.DRAFT,
            export_content="draft",
            source_summary={},
            annotations=(),
            ai_gateway_call_id=None,
            reviewed_by_user_id=None,
            reviewed_at=None,
            review_note=None,
        )

    async def build_evidence(self, *, student_id, period_start, period_end):
        return ExportEvidence(
            student_name="Amara",
            payload={"student": {"id": str(student_id), "name": "Amara"}},
        )

    async def create_export(self, **kwargs):
        self.record = IepExportRecord(
            id=self.record.id,
            student_id=kwargs["student_id"],
            requested_by_user_id=kwargs["requested_by_user_id"],
            period_start=kwargs["period_start"],
            period_end=kwargs["period_end"],
            status=IepExportStatus.DRAFT,
            export_content=kwargs["export_content"],
            source_summary=kwargs["source_summary"],
            annotations=(),
            ai_gateway_call_id=kwargs["ai_gateway_call_id"],
            reviewed_by_user_id=None,
            reviewed_at=None,
            review_note=None,
        )
        return self.record

    async def get_export(self, export_id):
        return self.record

    async def update_draft(self, **kwargs):
        return self.record

    async def finalize(self, **kwargs):
        self.record = IepExportRecord(
            id=self.record.id,
            student_id=self.record.student_id,
            requested_by_user_id=self.record.requested_by_user_id,
            period_start=self.record.period_start,
            period_end=self.record.period_end,
            status=IepExportStatus.FINAL,
            export_content=kwargs["export_content"] or self.record.export_content,
            source_summary=self.record.source_summary,
            annotations=self.record.annotations,
            ai_gateway_call_id=self.record.ai_gateway_call_id,
            reviewed_by_user_id=kwargs["senco_user_id"],
            reviewed_at=datetime(2026, 1, 31),
            review_note=kwargs["review_note"],
        )
        return self.record

    async def share(self, **kwargs):
        return type("Share", (), kwargs)()


@pytest.mark.asyncio
async def test_create_draft_generates_functional_document() -> None:
    repository = FakeRepository()
    service = IepExportService(
        repository=repository,
        gateway=FakeGateway(),
        compliance=FakeCompliance(),
    )
    student_id = uuid4()

    record = await service.create_draft(
        student_id=student_id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        actor_user_id=uuid4(),
        actor_role="teacher",
    )

    assert record.student_id == student_id
    assert record.status is IepExportStatus.DRAFT
    assert "short visual checks" in record.export_content


@pytest.mark.asyncio
async def test_only_senco_can_finalize() -> None:
    service = IepExportService(
        repository=FakeRepository(),
        gateway=FakeGateway(),
        compliance=FakeCompliance(),
    )

    with pytest.raises(ExportReviewRequiredError):
        await service.finalize(
            export_id=uuid4(),
            senco_user_id=uuid4(),
            actor_role="teacher",
            review_note=None,
            export_content=None,
        )


@pytest.mark.asyncio
async def test_share_requires_final_export() -> None:
    service = IepExportService(
        repository=FakeRepository(),
        gateway=FakeGateway(),
        compliance=FakeCompliance(),
    )

    with pytest.raises(ExportShareRequiresFinalError):
        await service.share(
            export_id=uuid4(),
            parent_id=uuid4(),
            actor_user_id=uuid4(),
            actor_role="teacher",
        )
