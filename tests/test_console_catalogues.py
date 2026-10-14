from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine

from nevo.api import frontend_unblockers
from nevo.api.product_learning import _upload_reason_code
from nevo.content_parsing.failures import UploadReasonCode, failure_code
from nevo.domain.accounts.vocabulary import UserRole
from nevo.domain.ask_nevo.vocabulary import AskNevoQuestionCategory
from nevo.domain.intelligence.pulse import PULSE_BANDS, pulse_label
from nevo.main import app


@pytest.mark.parametrize(
    "error,expected",
    [
        ("Lesson file exceeds 50 MB", "file_too_large"),
        ("Upload a TXT, PDF, DOCX, or PPTX file", "unsupported_file_type"),
        ("Could not read PDF text", "unreadable_file"),
        ("No readable lesson text was found", "no_readable_text"),
        ("ReadTimeout", "preparation_timeout"),
        ("429 too many requests", "service_busy"),
        ("UndefinedColumnError", "save_failed"),
        ("max_tokens", "output_limit"),
        ("Unexpected failure", "unknown"),
    ],
)
def test_failure_codes_cover_actual_refusals(error, expected):
    assert failure_code(error) == expected


def test_failed_and_partial_uploads_carry_reason_codes():
    failed = SimpleNamespace(status="failed", error_message="ReadTimeout", failure_reason=None)
    assert _upload_reason_code(failed) is UploadReasonCode.PREPARATION_TIMEOUT
    partial = SimpleNamespace(status="ready", structure={"failedPages": [2]})
    assert _upload_reason_code(partial) is UploadReasonCode.PARTIAL_READING
    assert _upload_reason_code(SimpleNamespace(status="ready", structure={})) is None


def test_published_bands_match_the_display_engine():
    for _, minimum, maximum, label in PULSE_BANDS:
        assert pulse_label(minimum) == label
        assert pulse_label(maximum - 0.01) == label
    assert pulse_label(100) == PULSE_BANDS[-1][3]


def test_catalogues_and_new_codes_are_in_openapi():
    spec = app.openapi()
    for path in (
        "/api/content/lessons/totals",
        "/api/v1/uploads/reason-codes",
        "/api/intelligence/help-categories",
        "/api/intelligence/pulse-thresholds",
    ):
        assert "get" in spec["paths"][path]
    schemas = spec["components"]["schemas"]
    assert set(schemas["UploadReasonCode"]["enum"]) == {code.value for code in UploadReasonCode}
    assert set(schemas["AskNevoQuestionCategory"]["enum"]) == {
        code.value for code in AskNevoQuestionCategory
    }
    assert "reasonCode" in schemas["BatchUploadItemResponse"]["properties"]
    assert "reasonCode" in schemas["UploadStatusResponse"]["properties"]


@pytest.mark.asyncio
async def test_library_counts_cover_more_than_200_and_do_not_double_count_assignments(monkeypatch):
    school_id, other_school = uuid4(), uuid4()
    actor = SimpleNamespace(id=uuid4(), school_id=school_id, role=UserRole.OTHER_ADMIN)
    monkeypatch.setattr(frontend_unblockers, "require_school_actor", AsyncMock(return_value=actor))
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        for ddl in (
            "CREATE TABLE lessons (id TEXT, school_id TEXT)",
            "CREATE TABLE lesson_assignments (id TEXT, lesson_id TEXT, class_id TEXT, "
            "status TEXT, available_from DATETIME)",
            "CREATE TABLE lesson_segments (id TEXT, lesson_id TEXT, "
            "needs_review BOOLEAN, approved_at DATETIME)",
            "CREATE TABLE lesson_key_points (id TEXT, lesson_id TEXT, review_state TEXT)",
        ):
            connection.exec_driver_sql(ddl)
        ids = [uuid4().hex for _ in range(205)]
        connection.exec_driver_sql(
            "INSERT INTO lessons VALUES (?, ?)", [(identifier, school_id.hex) for identifier in ids]
        )
        connection.exec_driver_sql(
            "INSERT INTO lessons VALUES (?, ?)", (uuid4().hex, other_school.hex)
        )
        assignments = [(uuid4().hex, ids[0], uuid4().hex, "assigned", None) for _ in range(3)]
        assignments.extend(
            [
                (uuid4().hex, ids[1], uuid4().hex, "cancelled", None),
                (
                    uuid4().hex,
                    ids[2],
                    uuid4().hex,
                    "assigned",
                    (datetime.now(UTC) + timedelta(days=7)).isoformat(),
                ),
            ]
        )
        connection.exec_driver_sql(
            "INSERT INTO lesson_assignments VALUES (?, ?, ?, ?, ?)", assignments
        )
        connection.exec_driver_sql(
            "INSERT INTO lesson_segments VALUES (?, ?, ?, ?)",
            [(uuid4().hex, ids[3], True, None) for _ in range(2)],
        )
        connection.exec_driver_sql(
            "INSERT INTO lesson_key_points VALUES (?, ?, ?)", (uuid4().hex, ids[3], "unsure")
        )

        async def execute(query):
            return connection.execute(query)

        result = await frontend_unblockers.library_totals(
            SimpleNamespace(), SimpleNamespace(execute=execute)
        )
        assert result == {"lessonsUploaded": 205, "liveToClasses": 1, "inReview": 1}
    engine.dispose()
