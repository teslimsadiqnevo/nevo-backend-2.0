from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from nevo.api.onboarding import _create_person
from nevo.domain.onboarding.vocabulary import OnboardingRowKind


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["active", "deactivated"])
async def test_import_leaves_existing_pupil_and_enrolment_untouched(status):
    child = SimpleNamespace(
        id=uuid4(),
        first_name="Original",
        last_name="Name",
        date_of_birth=date(2015, 1, 1),
        status=status,
    )
    original = vars(child).copy()
    session = SimpleNamespace(scalar=AsyncMock(return_value=child), add=Mock(), flush=AsyncMock())
    row = SimpleNamespace(
        kind=OnboardingRowKind.STUDENT,
        normalised_class_name="jss 2a",
        values={
            "first_name": "Changed",
            "last_name": "Changed",
            "date_of_birth": "2012-01-01",
            "admission_number": "ADM001",
        },
    )
    await _create_person(
        session, SimpleNamespace(id=uuid4()), row, {"jss 2a": SimpleNamespace(id=uuid4())}
    )
    assert vars(child) == original
    session.scalar.assert_awaited_once()
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_still_creates_a_missing_student_with_the_supplied_date():
    session = SimpleNamespace(scalar=AsyncMock(return_value=None), add=Mock(), flush=AsyncMock())
    row = SimpleNamespace(
        kind=OnboardingRowKind.STUDENT,
        normalised_class_name=None,
        values={
            "first_name": "New",
            "last_name": "Pupil",
            "date_of_birth": "2015-01-01",
            "admission_number": "ADM002",
        },
    )
    await _create_person(session, SimpleNamespace(id=uuid4()), row, {})
    created = session.add.call_args.args[0]
    assert created.first_name == "New"
    assert created.date_of_birth == date(2015, 1, 1)
    assert created.admission_number == "ADM002"
