import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from nevo.ai_gateway.compliance import ZeroTagCompliancePolicy


@dataclass(frozen=True, slots=True)
class ComplianceFinding:
    table: str
    record_id: UUID
    field: str
    term: str


@dataclass(frozen=True, slots=True)
class NdpaComplianceAudit:
    school_id: UUID
    school_name: str
    generated_at: datetime
    students_profiled: int
    adaptation_events_logged: int
    diagnostic_labels_stored: int
    findings: tuple[ComplianceFinding, ...]
    compliant: bool


@dataclass(frozen=True, slots=True)
class ComplianceSummary:
    school_id: UUID
    school_name: str
    students_profiled: int
    adaptation_events_logged: int


@dataclass(frozen=True, slots=True)
class ScannableRecord:
    table: str
    record_id: UUID
    field: str
    value: object


class NdpaComplianceAuditRepository(Protocol):
    async def summary(self, *, school_id: UUID) -> ComplianceSummary: ...

    async def scannable_records(
        self,
        *,
        school_id: UUID,
    ) -> tuple[ScannableRecord, ...]: ...


class NdpaComplianceAuditService:
    def __init__(
        self,
        repository: NdpaComplianceAuditRepository,
        *,
        compliance_policy: ZeroTagCompliancePolicy | None = None,
    ) -> None:
        self._repository = repository
        self._compliance_policy = compliance_policy or ZeroTagCompliancePolicy()

    async def summary(self, *, school_id: UUID) -> NdpaComplianceAudit:
        summary = await self._repository.summary(school_id=school_id)
        return _audit_from_summary(summary, findings=())

    async def scan(self, *, school_id: UUID) -> NdpaComplianceAudit:
        summary = await self._repository.summary(school_id=school_id)
        findings: list[ComplianceFinding] = []
        for record in await self._repository.scannable_records(school_id=school_id):
            text = _record_text(record.value)
            if not text:
                continue
            result = self._compliance_policy.inspect(text)
            findings.extend(
                ComplianceFinding(
                    table=record.table,
                    record_id=record.record_id,
                    field=record.field,
                    term=term,
                )
                for term in sorted(result.violations)
            )
        return _audit_from_summary(summary, findings=tuple(findings))

    async def report_pdf(self, *, school_id: UUID) -> bytes:
        return render_ndpa_compliance_pdf(await self.scan(school_id=school_id))


def render_ndpa_compliance_pdf(audit: NdpaComplianceAudit) -> bytes:
    status = "Compliant" if audit.compliant else "Review required"
    lines = [
        "Nevo NDPA 2023 Compliance Report",
        f"School: {audit.school_name}",
        f"Generated: {audit.generated_at.strftime('%Y-%m-%d %H:%M UTC')}",
        f"Students profiled: {audit.students_profiled}",
        f"Adaptation events logged: {audit.adaptation_events_logged}",
        f"Diagnostic labels found: {audit.diagnostic_labels_stored}",
        f"Status: {status}",
        (
            "No diagnostic labels were found in scanned student records. "
            "Nevo's Zero-Tag architecture remains compliant for this audit."
            if audit.compliant
            else "Diagnostic terminology was found and should be reviewed before filing."
        ),
    ]
    if audit.findings:
        lines.append("Findings:")
        lines.extend(
            f"{finding.table}.{finding.field}: {finding.term}"
            for finding in audit.findings[:12]
        )
    return _simple_pdf(lines)


def _audit_from_summary(
    summary: ComplianceSummary,
    *,
    findings: tuple[ComplianceFinding, ...],
) -> NdpaComplianceAudit:
    return NdpaComplianceAudit(
        school_id=summary.school_id,
        school_name=summary.school_name,
        generated_at=datetime.now(UTC),
        students_profiled=summary.students_profiled,
        adaptation_events_logged=summary.adaptation_events_logged,
        diagnostic_labels_stored=len(findings),
        findings=findings,
        compliant=not findings,
    )


def _record_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, default=str)


def _simple_pdf(lines: list[str]) -> bytes:
    y = 760
    content_lines = [
        "BT",
        "/F1 16 Tf",
        "1 0 0 1 72 800 Tm",
        f"({_pdf_escape(lines[0])}) Tj",
    ]
    content_lines.extend(["/F1 11 Tf"])
    for line in lines[1:]:
        y -= 22
        content_lines.append(f"1 0 0 1 72 {y} Tm ({_pdf_escape(line[:110])}) Tj")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("utf-8")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        (
            b"<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        ),
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")
    xref = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(pdf)


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
