"""Who supplies a parent's name, and where. SCRUM-189.

The earlier ruling was to hold the parent email until consent work resumed.
That was wrong, and this is the correction: the address is where the consent
request goes and consent gates activation, so it has a purpose the moment it
is entered. What was missing was the parent's name.

Three paths, three answers. The roster CSV asks for a first name and a surname
because a school filling that file has them to hand. The single enrol asks for
the email only, because a proprietor adding one child mid-term should not have
to go and find a full name. And the parent supplies their own name at consent,
which is the version the record keeps.
"""

from __future__ import annotations

import inspect

from nevo.api.consent import CompleteParentConsentRequest
from nevo.api.onboarding import (
    REQUIRED_STUDENT_COLUMNS,
    STUDENT_COLUMNS,
)
from nevo.api.product_admin import StudentEnroll
from nevo.main import app


def test_the_roster_asks_for_a_first_name_and_a_surname() -> None:
    # Renamed to guardian_* by SCRUM-203; still two columns, still optional.
    assert "guardian_first_name" in STUDENT_COLUMNS
    assert "guardian_last_name" in STUDENT_COLUMNS
    assert "parent_name" not in STUDENT_COLUMNS
    assert "guardian_name" not in STUDENT_COLUMNS


def test_a_missing_parent_name_does_not_lose_the_row() -> None:
    # A school filling four hundred rows will miss some, and the parent
    # confirms their own name at consent anyway.
    assert "guardian_first_name" not in REQUIRED_STUDENT_COLUMNS
    assert "guardian_last_name" not in REQUIRED_STUDENT_COLUMNS


def test_what_a_row_must_still_carry() -> None:
    # Date of birth, because age is derived from it. Parent email, because
    # activation depends on the consent request reaching somebody.
    assert "date_of_birth" in REQUIRED_STUDENT_COLUMNS
    assert "guardian_email" in REQUIRED_STUDENT_COLUMNS


def test_the_single_enrol_takes_an_email_and_not_a_name() -> None:
    fields = app.openapi()["components"]["schemas"]["StudentEnroll"]["properties"]

    assert "parentEmail" in fields
    assert "parentName" not in fields
    assert "parentFirstName" not in fields


def test_the_email_is_recorded_so_consent_has_somewhere_to_go() -> None:
    from nevo.api.product_admin import enroll_student

    source = inspect.getsource(enroll_student)

    assert "ParentLink(" in source
    assert "payload.parent_email" in source


def test_an_enrol_without_a_parent_email_still_works() -> None:
    # Optional: a school may not have it at the moment it adds the child.
    # The admission number is not optional - it is how the child identifies
    # themselves at the door, so there is no enrolling without one. SCRUM-202.
    enrol = StudentEnroll.model_validate(
        {
            "firstName": "Zainab",
            "lastName": "Bello",
            "classId": "00000000-0000-4000-8000-000000000001",
            "admissionNumber": "ADM001",
        }
    )

    assert enrol.parent_email is None


def test_the_parent_supplies_their_own_name_at_consent() -> None:
    request = CompleteParentConsentRequest.model_validate(
        {
            "token": "t" * 32,
            "grantedTypes": [],
            "parentName": "  Adaeze Bello  ",
        }
    )

    assert request.parent_name == "  Adaeze Bello  "


def test_the_parents_own_spelling_is_what_the_record_keeps() -> None:
    from nevo.consent.repositories import SqlAlchemyConsentRepository

    source = inspect.getsource(SqlAlchemyConsentRepository.complete_parent_request)

    # Their version, over a name a third party transcribed off a roster.
    assert "record.parent_name_on_form = parent_name.strip()" in source
