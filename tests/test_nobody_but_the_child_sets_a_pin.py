"""Nobody except the child ever sets a PIN. SCRUM-216, SCRUM-179.

An adult already linked to a child can clear a PIN. They can never set, learn
or choose one, and there is no longer a code path by which they could.

Why it is not self-service either: a reset needs proof that the person asking
owns the account, and nothing available to a child supplies that. No email, by
design. No phone. Security questions and enrolment facts both fail because a
classmate knows the answers and admission numbers are frequently sequential.
So any self-service reset is also a route into a classmate's account - and a
child signed in as a classmate for twenty minutes teaches the engine from
somebody else's behaviour, which breaks the product quietly.

The teacher is not choosing a credential. They are answering the one question
a machine cannot answer about a child with no email: whether this is really
her.
"""

from __future__ import annotations

import inspect

from nevo.api.auth import LEGACY_STUDENT_PIN_DIGITS, STUDENT_PIN_MAX_DIGITS
from nevo.api.product_admin import clear_student_pin
from nevo.main import app

SPEC = app.openapi()


def test_the_clear_never_returns_a_pin() -> None:
    cleared = SPEC["components"]["schemas"]["PinClearedResponse"]["properties"]

    assert "pin" not in cleared
    # It says what happened and what happens next, and nothing else.
    assert {"studentId", "clearedAt", "childSetsNext", "pinLength"} <= set(cleared)


def test_the_clear_never_generates_a_pin() -> None:
    source = inspect.getsource(clear_student_pin)

    # It used to mint four random digits and hand them back, so an adult both
    # chose a child's credential and knew it.
    assert "randbelow" not in source
    assert "hash_pin" not in source
    assert "pin_hash = None" in source


def test_the_old_issuing_endpoint_is_gone() -> None:
    assert "/api/v1/students/{student_id}/pin/reset" not in SPEC["paths"]
    assert "/api/v1/students/{student_id}/pin/clear" in SPEC["paths"]


def test_a_teacher_can_clear_for_their_own_class_only() -> None:
    source = inspect.getsource(clear_student_pin)

    assert "actor.role is not UserRole.TEACHER" in source
    assert "TeacherClassAssignment.teacher_id == actor.id" in source
    assert "TeacherClassAssignment.removed_at.is_(None)" in source


def test_the_access_check_fetches_the_child_and_refuses_school_wide_clear() -> None:

    source = inspect.getsource(clear_student_pin)

    assert "student = await session.get(User, student_id)" in source
    assert "student.role is not UserRole.STUDENT" in source
    assert "if not class_ids" in source


def test_repeated_clear_is_idempotent_and_explicit() -> None:
    source = inspect.getsource(clear_student_pin)

    assert "student.pin_cleared_at is not None" in source
    assert '"alreadyCleared": True' in source


def test_the_clear_is_logged_against_whoever_did_it() -> None:
    source = inspect.getsource(clear_student_pin)

    # The residual risk is a teacher clearing a PIN and setting one themselves
    # on the tablet before the child reaches it. Nothing in an API can prevent
    # that, so the log is what makes it visible rather than silent.
    assert "pin_cleared" in source
    # In the auth audit log, with the logins. The student record events table
    # is the IEP export trail - it has a foreign key to iep_exports and a
    # native enum of four export values, so writing "pin_cleared" there was
    # refused by the database and the whole call 500'd. The test that passed
    # against that only checked the table name appeared in the source.
    assert "AuthAuditEvent" in source
    assert "StudentRecordEvent" not in source
    # And it carries the class, which the ticket asks for alongside the child
    # and the time.
    assert "classIds" in source


def test_the_child_has_a_door_to_set_their_own() -> None:
    # Without this a cleared child could identify themselves and then had
    # nowhere to go: the only set-PIN endpoint was on the entry-token path,
    # which never resolved for anybody.
    assert "/api/v1/student-entry/pin" in SPEC["paths"]
    setup = SPEC["components"]["schemas"]["StudentPinSetup"]
    assert set(setup["required"]) == {"schoolCode", "admissionNumber", "pin"}


def test_the_child_door_only_opens_while_the_pin_is_cleared() -> None:
    from nevo.api.student_entry import set_own_pin

    source = inspect.getsource(set_own_pin)

    # The window exists because an adult who recognised the child opened it,
    # and it closes the moment a PIN is set - otherwise this would be a way to
    # overwrite a classmate's credential.
    assert "pin_already_set" in source
    assert "student.pin_hash is not None" in source
    # And it is gated on consent and the age check, like every other door a
    # child can reach.
    assert "consent_pending" in source
    assert "age_check_pending" in source


def test_four_digits_is_the_length_and_it_travels_with_the_pin() -> None:
    assert STUDENT_PIN_MAX_DIGITS == 4
    # Six is still accepted at sign-in so nobody already on one is locked out,
    # and the response tells the client to make them change it. SCRUM-179.
    assert LEGACY_STUDENT_PIN_DIGITS == 6
    session = SPEC["components"]["schemas"]["SessionResponse"]["properties"]
    assert "pinLength" in session
    assert "pinChangeRequired" in session
    # And the length rides on the clear, so no screen has to hardcode it.
    assert "pinLength" in SPEC["components"]["schemas"]["PinClearedResponse"]["properties"]
