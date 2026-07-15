from collections.abc import Iterable

from sqlalchemy import CheckConstraint, Enum, ForeignKeyConstraint, UniqueConstraint

from nevo.db import models  # noqa: F401
from nevo.db.base import Base


def enum_values(table_name: str, column_name: str) -> list[str]:
    column = Base.metadata.tables[table_name].columns[column_name]
    assert isinstance(column.type, Enum)
    return list(column.type.enums)


def unique_column_sets(table_name: str) -> set[tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def check_names(table_name: str) -> Iterable[str]:
    table = Base.metadata.tables[table_name]
    for constraint in table.constraints:
        if isinstance(constraint, CheckConstraint) and constraint.name:
            yield constraint.name


def foreign_key_targets(table_name: str) -> set[tuple[str, str]]:
    table = Base.metadata.tables[table_name]
    targets: set[tuple[str, str]] = set()
    for constraint in table.constraints:
        if isinstance(constraint, ForeignKeyConstraint):
            for element in constraint.elements:
                targets.add((element.column.table.name, element.column.name))
    return targets


def test_core_tables_exist() -> None:
    for table_name in (
        "schools",
        "users",
        "classes",
        "student_class_enrollments",
        "consent_records",
    ):
        assert table_name in Base.metadata.tables


def test_user_role_enum_is_exact() -> None:
    assert enum_values("users", "role") == [
        "student",
        "teacher",
        "senco_admin",
        "other_admin",
        "parent_guardian",
    ]


def test_auth_method_enum_is_shared_and_exact() -> None:
    assert enum_values("users", "auth_method") == ["email_password", "pin", "sso"]
    assert enum_values("schools", "auth_method") == ["email_password", "pin", "sso"]


def test_consent_enums_are_exact() -> None:
    assert enum_values("consent_records", "status") == ["pending", "confirmed"]
    assert enum_values("consent_records", "confirmed_via") == [
        "written",
        "verbal",
        "email",
        "digital",
    ]


def test_unique_constraints_present() -> None:
    assert ("school_code",) in unique_column_sets("schools")
    assert ("school_url_slug",) in unique_column_sets("schools")
    assert ("email",) in unique_column_sets("users")
    assert ("student_id", "class_id") in unique_column_sets(
        "student_class_enrollments"
    )
    assert ("subject_user_id", "consent_type") in unique_column_sets(
        "consent_records"
    )


def test_state_invariants_have_database_checks() -> None:
    assert "ck_users_deactivated_at_matches_status" in set(check_names("users"))
    assert "ck_consent_records_confirmation_fields_match_status" in set(
        check_names("consent_records")
    )


def test_users_and_classes_reference_schools() -> None:
    assert ("schools", "id") in foreign_key_targets("users")
    assert ("schools", "id") in foreign_key_targets("classes")


def test_learner_profiles_now_reference_users() -> None:
    # SCRUM-15 deferred this foreign key until the users table existed.
    assert ("users", "id") in foreign_key_targets("learner_profiles")
    assert ("users", "id") in foreign_key_targets("learner_profile_history")


def test_profile_attention_flags_reference_profile_session_and_student() -> None:
    assert ("users", "id") in foreign_key_targets(
        "learner_profile_attention_flags"
    )
    assert ("learner_profiles", "id") in foreign_key_targets(
        "learner_profile_attention_flags"
    )
    assert ("lesson_sessions", "id") in foreign_key_targets(
        "learner_profile_attention_flags"
    )
    assert enum_values("learner_profile_attention_flags", "status") == [
        "open",
        "reviewed",
        "dismissed",
    ]
