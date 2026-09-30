"""Nothing reaches anyone until the school has paid.

A school could create classes, add teachers and add students without paying
anything, so the order is now upload, derive, confirm, pay, activate. The two
things worth guarding are that the derivation reads a school's own file
faithfully, and that activation is refused by the server rather than by a
hidden button.
"""

from __future__ import annotations

import inspect

import pytest

from nevo.api.onboarding import (
    REQUIRED_STUDENT_COLUMNS,
    STUDENT_COLUMNS,
    TEACHER_COLUMNS,
    _derived_classes,
    _read_rows,
    activate,
)
from nevo.domain.onboarding.vocabulary import OnboardingRowKind, OnboardingStage
from nevo.main import app

STUDENTS = (
    b"first_name,last_name,class,date_of_birth,admission_number,"
    b"guardian_first_name,guardian_last_name,guardian_email,guardian_relationship\n"
    b"Amara,Okafor,JSS 1A,2015-04-23,ADM001,Ngozi,Okafor,ngozi@example.com,Mother\n"
    b"Tunde,Bello,jss 1a ,2015-06-02,ADM002,Bisi,Bello,bisi@example.com,Mother\n"
    # No guardian name, and the row still stands: SCRUM-189.
    b"Chidi,Eze,JSS  2B,2014-11-30,ADM003,,,uche@example.com,\n"
    b"Sade,Adeyemi,,2015-01-09,ADM004,Kemi,Adeyemi,kemi@example.com,Mother\n"
)


@pytest.fixture(scope="module")
def spec() -> dict:
    return app.openapi()


def test_a_guardian_contact_is_mandatory_and_a_guardian_name_is_not() -> None:
    # A child whose guardian cannot be reached cannot be consented for, so the
    # address is required. The name is asked for and not insisted on: the
    # parent supplies their own at account setup. SCRUM-189, SCRUM-203.
    assert "guardian_first_name" in STUDENT_COLUMNS
    assert "guardian_last_name" in STUDENT_COLUMNS
    assert "guardian_email" in REQUIRED_STUDENT_COLUMNS
    assert "guardian_first_name" not in REQUIRED_STUDENT_COLUMNS
    # The child's own identifier, which is how they sign in.
    assert "admission_number" in REQUIRED_STUDENT_COLUMNS
    assert "guardian_email" not in TEACHER_COLUMNS


def test_the_class_list_is_read_out_of_the_school_own_file() -> None:
    rows = _read_rows(STUDENTS, OnboardingRowKind.STUDENT)

    derived = _derived_classes(rows)

    # JSS 1A, "jss 1a " and "JSS  1A" are one class, not three.
    assert [item.normalised_name for item in derived] == ["jss 1a", "jss 2b"]
    assert derived[0].student_count == 2
    assert derived[0].year_group == "JSS 1"
    assert derived[0].section == "A"


def test_a_row_without_a_class_is_rejected_by_line_and_reason() -> None:
    rows = _read_rows(STUDENTS, OnboardingRowKind.STUDENT)

    rejected = [row for row in rows if row.rejected]

    assert len(rejected) == 1
    assert rejected[0].row_number == 5
    assert rejected[0].rejection_field == "class"
    # A school with four hundred children will not notice thirty going
    # missing, so the row says which line and what to do.
    assert "Row 5" in (rejected[0].rejection_reason or "")


def test_a_rejected_row_is_not_counted_or_charged_for() -> None:
    rows = _read_rows(STUDENTS, OnboardingRowKind.STUDENT)

    assert sum(1 for row in rows if row.countable) == 3


def test_a_file_missing_its_columns_says_which() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as refusal:
        _read_rows(b"first_name,last_name\nAmara,Okafor\n", OnboardingRowKind.STUDENT)

    assert refusal.value.detail["code"] == "missing_columns"
    assert "class" in refusal.value.detail["missingColumns"]


def test_activation_is_refused_by_the_server_until_the_invoice_is_paid() -> None:
    source = inspect.getsource(activate)

    assert "InvoiceStatus.PAID" in source
    assert "payment_outstanding" in source


def test_the_stages_are_the_ruled_order() -> None:
    assert [stage.value for stage in OnboardingStage] == [
        "uploading",
        "confirmed",
        "awaiting_payment",
        "activated",
    ]


def test_the_console_is_told_what_it_may_do_next(spec: dict) -> None:
    fields = spec["components"]["schemas"]["OnboardingState"]["properties"]

    # Decided here rather than inferred by the console from empty arrays.
    assert {"canConfirm", "canPay", "canActivate", "stage"} <= set(fields)


def test_the_school_can_correct_the_derived_list_before_committing(spec: dict) -> None:
    assert "patch" in spec["paths"]["/api/v1/onboarding/classes"]
    assert "post" in spec["paths"]["/api/v1/onboarding/confirm"]


def test_a_mid_term_addition_can_be_priced_before_it_is_confirmed(spec: dict) -> None:
    assert "post" in spec["paths"]["/api/v1/onboarding/additions/quote"]
    fields = spec["components"]["schemas"]["AdditionQuote"]["properties"]

    assert {"students", "teachers", "amount"} <= set(fields)
