from datetime import UTC, datetime
from uuid import uuid4

from nevo.intelligence.compliance_audit import (
    ComplianceFinding,
    NdpaComplianceAudit,
    render_ndpa_compliance_pdf,
)
from nevo.main import app


def test_admin_launch_contracts_are_declared_in_openapi() -> None:
    schema = app.openapi()
    paths = schema["paths"]

    assert "post" in paths["/api/v1/admin/team/{target_user_id}/deactivate"]
    assert "post" in paths["/api/v1/admin/team/{target_user_id}/restore"]
    assert "get" in paths["/api/v1/students/sign-in-details"]
    assert "get" in paths["/api/v1/school/dpa-agreement"]
    assert "post" in paths["/api/v1/teachers/{teacher_id}/restore"]
    assert set(paths["/api/v1/teachers/{teacher_id}/subjects"]) == {
        "get",
        "post",
        "put",
    }
    assert "get" in paths["/api/billing/invoices/{invoice_id}/bank-transfer-details"]
    assert "post" in paths["/api/billing/payments/transfer-report"]
    assert "get" in paths["/api/billing/payments/transfer-reports"]


def test_student_and_teacher_reads_expose_the_requested_fields() -> None:
    schemas = app.openapi()["components"]["schemas"]

    for name in ("StudentSummaryResponse", "StudentDetailResponse", "ClassStudentResponse"):
        assert "admissionNumber" in schemas[name]["properties"]
    assert "subjects" in schemas["TeacherDetailResponse"]["properties"]
    assert "subject" in schemas["AssignedTeacherResponse"]["properties"]
    assert "subject" in schemas["AssignedClassResponse"]["properties"]


def test_compliance_pdf_never_exports_finding_terms_or_record_ids() -> None:
    record_id = uuid4()
    pdf = render_ndpa_compliance_pdf(
        NdpaComplianceAudit(
            school_id=uuid4(),
            school_name="Example School",
            generated_at=datetime(2026, 10, 9, tzinfo=UTC),
            students_profiled=1,
            adaptation_events_logged=2,
            diagnostic_labels_stored=1,
            findings=(
                ComplianceFinding(
                    table="learner_profiles",
                    record_id=record_id,
                    field="profile",
                    term="forbidden-term",
                ),
            ),
            compliant=False,
        )
    )

    assert str(record_id).encode() not in pdf
    assert b"forbidden-term" not in pdf
