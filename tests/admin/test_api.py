from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nevo.api.admin import AdminOversightDependency, router
from nevo.api.auth import authenticated_principal
from nevo.auth.entities import AuthPrincipal
from nevo.intelligence.adaptation_log import AdaptationEventLogService
from nevo.intelligence.compliance_audit import (
    ComplianceFinding,
    ComplianceSummary,
    NdpaComplianceAuditService,
    render_ndpa_compliance_pdf,
)
from nevo.intelligence.entities import AdaptationEventLogRecord
from nevo.permissions.entities import PermissionSnapshot

USER_ID = uuid4()
SCHOOL_ID = uuid4()


class FakeAdaptationEventLogService(AdaptationEventLogService):
    def __init__(self) -> None:
        self.calls = []

    async def events(self, **kwargs):
        self.calls.append(kwargs)
        return (
            (
                AdaptationEventLogRecord(
                    id=uuid4(),
                    student_id=kwargs["student_id"] or uuid4(),
                    student_first_name="Amara",
                    lesson_id=kwargs["lesson_id"] or uuid4(),
                    lesson_title="Fractions Lesson 3",
                    timestamp=datetime(2026, 8, 22, 10, 23, tzinfo=UTC),
                    trigger="Comprehension declining + engagement drop",
                    adaptation="Text -> Visual",
                    event_type="modality_suggestion_shown",
                ),
            ),
            847,
        )


class FakeComplianceRepository:
    async def summary(self, *, school_id):
        return ComplianceSummary(
            school_id=school_id,
            school_name="Nevo Academy",
            students_profiled=247,
            adaptation_events_logged=1843,
        )

    async def scannable_records(self, *, school_id):
        return ()


class FakeNdpaComplianceAuditService(NdpaComplianceAuditService):
    def __init__(self) -> None:
        super().__init__(FakeComplianceRepository())


def client_for(
    *,
    school_id=SCHOOL_ID,
    role="other_admin",
) -> tuple[TestClient, FakeAdaptationEventLogService]:
    principal = AuthPrincipal(user_id=USER_ID, role=role, session_id=uuid4())
    service = FakeAdaptationEventLogService()
    compliance_service = FakeNdpaComplianceAuditService()
    app = FastAPI()
    app.state.adaptation_event_log_service = service
    app.state.ndpa_compliance_audit_service = compliance_service
    app.dependency_overrides[authenticated_principal] = lambda: principal
    dependency = AdminOversightDependency.__metadata__[0].dependency
    app.dependency_overrides[dependency] = lambda: PermissionSnapshot(
        user_id=principal.user_id,
        school_id=school_id,
        role=principal.role,
        status="active",
        school_auth_method="email_password",
        assigned_scopes=frozenset(),
    )
    app.include_router(router)
    return TestClient(app), service


def test_admin_adaptation_log_returns_table_rows_and_filters() -> None:
    client, service = client_for()
    class_id = uuid4()
    student_id = uuid4()
    lesson_id = uuid4()

    response = client.get(
        "/api/admin/adaptation-log",
        params={
            "classId": str(class_id),
            "studentId": str(student_id),
            "lessonId": str(lesson_id),
            "dateFrom": "2026-08-22T00:00:00Z",
            "dateTo": "2026-08-22T23:59:59Z",
            "limit": 20,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 847
    assert body["events"][0]["studentFirstName"] == "Amara"
    assert body["events"][0]["lessonTitle"] == "Fractions Lesson 3"
    assert body["events"][0]["trigger"] == "Comprehension declining + engagement drop"
    assert body["events"][0]["adaptation"] == "Text -> Visual"
    call = service.calls[0]
    assert call["school_id"] == SCHOOL_ID
    assert call["class_id"] == class_id
    assert call["student_id"] == student_id
    assert call["lesson_id"] == lesson_id


def test_admin_adaptation_log_requires_school_context() -> None:
    client, _ = client_for(school_id=None)

    response = client.get("/api/admin/adaptation-log")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "school_context_required"


def test_admin_compliance_audit_summary_returns_zero_label_metrics() -> None:
    client, _ = client_for()

    response = client.get("/api/admin/compliance-audit")

    assert response.status_code == 200
    body = response.json()
    assert body["schoolName"] == "Nevo Academy"
    assert body["studentsProfiled"] == 247
    assert body["adaptationEventsLogged"] == 1843
    assert body["diagnosticLabelsStored"] == 0
    assert body["compliant"] is True


def test_admin_compliance_audit_scan_returns_findings_when_terms_exist() -> None:
    class FindingService(FakeNdpaComplianceAuditService):
        async def scan(self, *, school_id):
            audit = await super().summary(school_id=school_id)
            finding = ComplianceFinding(
                table="attention_flags",
                record_id=uuid4(),
                field="description",
                term="diagnosis",
            )
            return type(audit)(
                school_id=audit.school_id,
                school_name=audit.school_name,
                generated_at=audit.generated_at,
                students_profiled=audit.students_profiled,
                adaptation_events_logged=audit.adaptation_events_logged,
                diagnostic_labels_stored=1,
                findings=(finding,),
                compliant=False,
            )

    client, _ = client_for()
    client.app.state.ndpa_compliance_audit_service = FindingService()

    response = client.post("/api/admin/compliance-audit/scan")

    assert response.status_code == 200
    body = response.json()
    assert body["diagnosticLabelsStored"] == 1
    assert body["compliant"] is False
    assert body["findings"][0]["table"] == "attention_flags"


def test_admin_compliance_audit_report_exports_pdf() -> None:
    client, _ = client_for()

    response = client.get("/api/admin/compliance-audit/report.pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert b"Nevo NDPA 2023 Compliance Report" in response.content


def test_render_ndpa_compliance_pdf_includes_summary_text() -> None:
    service = FakeNdpaComplianceAuditService()

    import asyncio

    audit = asyncio.run(service.summary(school_id=SCHOOL_ID))
    pdf = render_ndpa_compliance_pdf(audit)

    assert pdf.startswith(b"%PDF")
    assert b"Nevo Academy" in pdf
