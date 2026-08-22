# NDPA Compliance Audit Screen Backend

Implemented the backend contract for the school admin Data Compliance screen.

## API Contract

- `GET /api/admin/compliance-audit`
  - Returns school name, total students profiled, total adaptation events logged, diagnostic labels stored, compliance status, and findings.
- `POST /api/admin/compliance-audit/scan`
  - Runs a Zero-Tag scan across student-scoped text and JSON records.
  - Uses the existing diagnostic terminology policy.
  - Returns findings with table, record id, field, and term when anything needs review.
- `GET /api/admin/compliance-audit/report.pdf`
  - Runs the scan and returns an NDPA 2023 compliance PDF report.

All endpoints require the existing school admin oversight permission and a school context.

## Scan Coverage

The scan checks stored fields where diagnostic labels could leak into school-facing records:

- learner profile history notes
- profile attention flag rationale
- attention flag descriptions
- escalation teacher notes
- intervention recommendation text
- progress export content, summaries, annotations, and review notes
- student record event payloads
- signal event payloads
- Ask Nevo page/context metadata

## PDF Export

The PDF report includes:

- school name
- generation date
- students profiled
- adaptation events logged
- diagnostic labels found
- compliance statement for NDPA 2023 records

The report is generated in-process to avoid adding a deployment dependency.
