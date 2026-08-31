"""Retention anonymisation tests."""
from datetime import UTC, datetime, timedelta

from nevo.db.models.account import User
from nevo.domain.accounts.vocabulary import AuthMethod, UserRole, UserStatus
from nevo.retention.anonymisation import anonymise_student
from nevo.retention.service import RetentionService

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


def _student(**overrides: object) -> User:
    student = User(
        role=UserRole.STUDENT,
        auth_method=AuthMethod.PIN,
        status=UserStatus.ACTIVE,
        first_name="Ada",
        last_name="Lovelace",
        email="ada@school.test",
        login_identifier="ada.lovelace",
        password_hash="hash",
        pin_hash="pin-hash",
        sso_external_id="sso-123",
        baseline_profile={"reading": 4},
        engine_config={"pace": "slow"},
        preferences={"theme": "dark"},
    )
    for key, value in overrides.items():
        setattr(student, key, value)
    return student


def test_anonymisation_strips_every_direct_identifier() -> None:
    student = _student()

    anonymise_student(student, now=NOW)

    assert student.first_name == "Former"
    assert student.last_name == "Student"
    assert student.email is None
    assert student.password_hash is None
    assert student.pin_hash is None
    assert student.sso_external_id is None
    assert student.baseline_profile == {}
    assert student.engine_config == {}
    assert student.preferences == {}
    assert student.login_identifier is not None
    assert student.login_identifier.startswith("deleted-")


def test_anonymisation_marks_the_row_and_deactivates() -> None:
    student = _student()

    anonymise_student(student, now=NOW)

    assert student.status is UserStatus.DEACTIVATED
    assert student.anonymised_at == NOW
    assert student.deactivated_at == NOW


def test_anonymisation_keeps_the_original_leaving_date() -> None:
    left_at = NOW - timedelta(days=400)
    student = _student(deactivated_at=left_at)

    anonymise_student(student, now=NOW)

    assert student.deactivated_at == left_at
    assert student.anonymised_at == NOW


def test_login_identifiers_do_not_collide() -> None:
    first, second = _student(), _student()

    anonymise_student(first, now=NOW)
    anonymise_student(second, now=NOW)

    assert first.login_identifier != second.login_identifier


def test_record_is_expired_only_after_the_retention_window() -> None:
    is_expired = RetentionService._is_expired

    assert not is_expired(NOW - timedelta(days=364), 365, NOW)
    assert is_expired(NOW - timedelta(days=365), 365, NOW)
    assert is_expired(NOW - timedelta(days=400), 365, NOW)


def test_a_student_who_never_left_is_never_expired() -> None:
    assert not RetentionService._is_expired(None, 365, NOW)


def test_naive_timestamps_are_treated_as_utc() -> None:
    naive = datetime(2025, 1, 1, 12, 0)

    assert RetentionService._is_expired(naive, 365, NOW)


def test_a_shorter_school_window_expires_sooner() -> None:
    left_at = NOW - timedelta(days=100)

    assert RetentionService._is_expired(left_at, 90, NOW)
    assert not RetentionService._is_expired(left_at, 365, NOW)
