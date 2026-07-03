from collections.abc import Iterable

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint

from nevo.db import models  # noqa: F401
from nevo.db.base import Base


def unique_column_sets(table_name: str) -> set[tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def foreign_key_targets(table_name: str) -> set[tuple[str, str]]:
    table = Base.metadata.tables[table_name]
    targets: set[tuple[str, str]] = set()
    for constraint in table.constraints:
        if isinstance(constraint, ForeignKeyConstraint):
            for element in constraint.elements:
                targets.add((element.column.table.name, element.column.name))
    return targets


def check_names(table_name: str) -> Iterable[str]:
    table = Base.metadata.tables[table_name]
    for constraint in table.constraints:
        if isinstance(constraint, CheckConstraint) and constraint.name:
            yield constraint.name


def index_names(table_name: str) -> set[str]:
    return {
        index.name
        for index in Base.metadata.tables[table_name].indexes
        if isinstance(index, Index) and index.name
    }


def test_auth_tables_and_school_scoped_identifier_exist() -> None:
    for table_name in (
        "auth_sessions",
        "auth_login_attempts",
        "auth_audit_events",
    ):
        assert table_name in Base.metadata.tables

    users = Base.metadata.tables["users"]
    assert "login_identifier" in users.columns
    assert ("school_id", "login_identifier") in unique_column_sets("users")
    assert "uq_schools_school_code_ci" in index_names("schools")
    assert "uq_users_email_ci" in index_names("users")
    assert "uq_users_school_login_identifier_ci" in index_names("users")


def test_sessions_reference_users_and_replacement_session() -> None:
    targets = foreign_key_targets("auth_sessions")
    assert ("users", "id") in targets
    assert ("auth_sessions", "id") in targets


def test_session_invariants_are_database_enforced() -> None:
    check_constraints = set(check_names("auth_sessions"))
    assert "ck_auth_sessions_expiry_after_creation" in check_constraints
    assert "ck_auth_sessions_revocation_fields_consistent" in check_constraints
    assert "uq_auth_sessions_one_active_student" in index_names("auth_sessions")


def test_auth_storage_has_no_raw_secret_columns() -> None:
    for table_name in (
        "auth_sessions",
        "auth_login_attempts",
        "auth_audit_events",
    ):
        columns = set(Base.metadata.tables[table_name].columns.keys())
        assert "password" not in columns
        assert "pin" not in columns
        assert "access_token" not in columns
        assert "ip_address" not in columns

    token_digest = Base.metadata.tables["auth_sessions"].columns["token_digest"]
    assert token_digest.type.length == 64
