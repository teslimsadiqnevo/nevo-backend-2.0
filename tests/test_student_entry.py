"""A child follows a link and types nothing about themselves.

Entry asked a child for their name and their age, both of which the school had
already given Nevo. It also let routing decide whether a child whose parent
had not consented could start, which a direct URL walks straight past.
"""

from __future__ import annotations

import inspect
from datetime import date

import pytest

from nevo.api.onboarding import STUDENT_COLUMNS, _read_rows
from nevo.api.student_entry import age_on, set_pin_and_start
from nevo.db.models.account import User
from nevo.db.models.product import StudentOnboardingGrant
from nevo.domain.onboarding.vocabulary import OnboardingRowKind
from nevo.main import app


@pytest.fixture(scope="module")
def spec() -> dict:
    return app.openapi()


def test_the_link_belongs_to_a_child_not_just_a_class() -> None:
    columns = {column.name for column in StudentOnboardingGrant.__table__.columns}

    assert "student_id" in columns


def test_the_roster_carries_the_date_of_birth() -> None:
    assert "date_of_birth" in {column.name for column in User.__table__.columns}
    assert "date_of_birth" in STUDENT_COLUMNS


@pytest.mark.parametrize(
    ("born", "today", "age"),
    [
        (date(2015, 4, 23), date(2026, 9, 21), 11),
        (date(2015, 9, 21), date(2026, 9, 21), 11),
        (date(2015, 9, 22), date(2026, 9, 21), 10),
    ],
)
def test_age_is_derived_the_way_a_person_counts_it(born: date, today: date, age: int) -> None:
    assert age_on(born, today) == age


def test_a_missing_date_of_birth_is_refused_at_import_not_asked_of_the_child() -> None:
    rows = _read_rows(
        b"first_name,last_name,class,date_of_birth,parent_name,parent_email\n"
        b"Amara,Okafor,JSS 1A,,Ngozi Okafor,ngozi@example.com\n",
        OnboardingRowKind.STUDENT,
    )

    assert rows[0].rejected
    assert rows[0].rejection_field == "date_of_birth"


def test_a_date_written_the_way_a_school_writes_it_is_read() -> None:
    rows = _read_rows(
        b"first_name,last_name,class,date_of_birth,parent_name,parent_email\n"
        b"Amara,Okafor,JSS 1A,23/04/2015,Ngozi Okafor,ngozi@example.com\n"
        b"Tunde,Bello,JSS 1A,not a date,Bisi Bello,bisi@example.com\n",
        OnboardingRowKind.STUDENT,
    )

    assert not rows[0].rejected
    assert rows[1].rejected
    assert rows[1].rejection_field == "date_of_birth"


def test_the_link_resolves_to_the_child_rather_than_asking_them(spec: dict) -> None:
    fields = spec["components"]["schemas"]["StudentEntryState"]["properties"]

    assert {"firstName", "className", "consentState", "age"} <= set(fields)


def test_consent_is_enforced_by_the_api_not_by_routing() -> None:
    source = inspect.getsource(set_pin_and_start)

    assert "_has_consent" in source
    assert "consent_pending" in source


def test_a_waiting_child_is_told_nothing_about_themselves() -> None:
    source = inspect.getsource(set_pin_and_start)

    # Anyone holding the link can open this screen, so the refusal carries
    # the state and nothing else.
    assert "grown-up at home" in source
