from datetime import date, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nevo.api.auth import authenticated_principal
from nevo.api.exports import router
from nevo.auth.entities import AuthPrincipal
from nevo.domain.exports.vocabulary import IepExportShareStatus, IepExportStatus
from nevo.exports.entities import IepExportRecord, IepExportShareRecord
from nevo.exports.service import IepExportService


class FakeIepExportService(IepExportService):
    def __init__(self) -> None:
        self.requests = []

    async def create_draft(self, **kwargs):
        self.requests.append(("create", kwargs))
        return _export(status=IepExportStatus.DRAFT, student_id=kwargs["student_id"])

    async def get_export(self, **kwargs):
        self.requests.append(("get", kwargs))
        return _export(status=IepExportStatus.DRAFT)

    async def update_draft(self, **kwargs):
        self.requests.append(("update", kwargs))
        return _export(status=IepExportStatus.DRAFT, export_content="edited")

    async def finalize(self, **kwargs):
        self.requests.append(("finalize", kwargs))
        return _export(
            status=IepExportStatus.FINAL,
            reviewed_by_user_id=kwargs["senco_user_id"],
            review_note=kwargs["review_note"],
        )

    async def share(self, **kwargs):
        self.requests.append(("share", kwargs))
        return IepExportShareRecord(
            id=uuid4(),
            export_id=kwargs["export_id"],
            student_id=uuid4(),
            parent_id=kwargs["parent_id"],
            shared_by_user_id=kwargs["actor_user_id"],
            status=IepExportShareStatus.SHARED,
            shared_at=datetime(2026, 1, 31),
        )


def _export(
    *,
    status: IepExportStatus,
    student_id=None,
    export_content="draft",
    reviewed_by_user_id=None,
    review_note=None,
) -> IepExportRecord:
    return IepExportRecord(
        id=uuid4(),
        student_id=student_id or uuid4(),
        requested_by_user_id=uuid4(),
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        status=status,
        export_content=export_content,
        source_summary={"signalTrends": []},
        annotations=(),
        ai_gateway_call_id=uuid4(),
        reviewed_by_user_id=reviewed_by_user_id,
        reviewed_at=datetime(2026, 1, 31)
        if reviewed_by_user_id is not None
        else None,
        review_note=review_note,
    )


def client_for(role: str = "teacher") -> tuple[TestClient, FakeIepExportService]:
    principal = AuthPrincipal(
        user_id=uuid4(),
        role=role,
        session_id=uuid4(),
    )
    service = FakeIepExportService()
    app = FastAPI()
    app.state.iep_export_service = service
    app.dependency_overrides[authenticated_principal] = lambda: principal
    app.include_router(router)
    return TestClient(app), service


def test_create_export_endpoint_returns_draft() -> None:
    client, service = client_for()
    student_id = uuid4()

    response = client.post(
        "/api/v1/exports/iep",
        json={
            "studentId": str(student_id),
            "periodStart": "2026-01-01",
            "periodEnd": "2026-01-31",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "draft"
    assert response.json()["studentId"] == str(student_id)
    assert service.requests[0][0] == "create"


def test_review_endpoint_logs_senco_identity() -> None:
    client, _ = client_for(role="senco_admin")
    export_id = uuid4()

    response = client.post(
        f"/api/v1/exports/iep/{export_id}/review",
        json={"reviewNote": "Ready for family sharing."},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "final"
    assert response.json()["reviewedByUserId"] is not None


def test_share_endpoint_returns_parent_share_record() -> None:
    client, _ = client_for()
    export_id = uuid4()
    parent_id = uuid4()

    response = client.post(
        f"/api/v1/exports/iep/{export_id}/share",
        json={"parentId": str(parent_id)},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "shared"
    assert response.json()["parentId"] == str(parent_id)
