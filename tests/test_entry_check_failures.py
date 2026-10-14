from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request, Response
from sqlalchemy.exc import SQLAlchemyError

from nevo.api import student_entry


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["student", "class", "consent"])
async def test_failed_entry_checks_never_admit_the_child(monkeypatch, stage):
    error = SQLAlchemyError("Lookup unavailable")
    student = SimpleNamespace(id=uuid4())
    scalar = AsyncMock(
        side_effect=[error]
        if stage == "student"
        else [student, error]
        if stage == "class"
        else [student, None]
    )
    session = SimpleNamespace(scalar=scalar, rollback=AsyncMock())
    monkeypatch.setattr(student_entry, "_throttle", AsyncMock())
    monkeypatch.setattr(student_entry, "_record", AsyncMock())
    if stage == "consent":
        monkeypatch.setattr(student_entry, "_consent_state", AsyncMock(side_effect=error))
    payload = student_entry.StudentEntryLookup(schoolCode="NV-E2E000", admissionNumber="E2E/PROBE")
    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})
    with pytest.raises(HTTPException) as failure:
        await student_entry.lookup_entry(payload, request, Response(), session)
    assert failure.value.status_code == 503
    assert failure.value.detail["code"] == "entry_check_failed"
    session.rollback.assert_awaited_once()
