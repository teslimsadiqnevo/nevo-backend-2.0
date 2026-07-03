from collections.abc import Iterable

from sqlalchemy import CheckConstraint, Enum, ForeignKeyConstraint, Index

from nevo.db import models  # noqa: F401
from nevo.db.base import Base


def enum_values(table_name: str, column_name: str) -> list[str]:
    column = Base.metadata.tables[table_name].columns[column_name]
    assert isinstance(column.type, Enum)
    return list(column.type.enums)


def foreign_key_targets(table_name: str) -> set[tuple[str, str]]:
    table = Base.metadata.tables[table_name]
    targets: set[tuple[str, str]] = set()
    for constraint in table.constraints:
        if isinstance(constraint, ForeignKeyConstraint):
            for element in constraint.elements:
                targets.add((element.column.table.name, element.column.name))
    return targets


def check_names(table_name: str) -> Iterable[str]:
    for constraint in Base.metadata.tables[table_name].constraints:
        if isinstance(constraint, CheckConstraint) and constraint.name:
            yield constraint.name


def index_names(table_name: str) -> set[str]:
    return {
        index.name
        for index in Base.metadata.tables[table_name].indexes
        if isinstance(index, Index) and index.name
    }


def test_permission_tables_exist() -> None:
    for table_name in (
        "admins",
        "admin_scope_assignments",
        "admin_invitations",
    ):
        assert table_name in Base.metadata.tables


def test_permission_scope_enum_is_exact() -> None:
    assert enum_values("admin_scope_assignments", "scope") == [
        "billing",
        "roster",
        "curriculum",
        "senco",
        "it_sso",
        "oversight",
        "teacher",
    ]


def test_permission_foreign_keys_are_tenant_anchored() -> None:
    assert ("users", "id") in foreign_key_targets("admins")
    assert ("schools", "id") in foreign_key_targets("admins")
    assert ("admins", "id") in foreign_key_targets("admin_scope_assignments")
    assert ("users", "id") in foreign_key_targets("admin_invitations")
    assert ("schools", "id") in foreign_key_targets("admin_invitations")


def test_active_scope_and_invitation_uniqueness_are_indexed() -> None:
    assert "uq_admin_scope_assignments_active" in index_names(
        "admin_scope_assignments"
    )
    assert "uq_admin_invitations_active_user" in index_names(
        "admin_invitations"
    )


def test_history_and_invitation_state_checks_exist() -> None:
    assert "ck_admin_scope_assignments_revoked_after_grant" in set(
        check_names("admin_scope_assignments")
    )
    invitation_checks = set(check_names("admin_invitations"))
    assert "ck_admin_invitations_expiry_after_creation" in invitation_checks
    assert "ck_admin_invitations_not_accepted_and_revoked" in invitation_checks


def test_invitation_storage_contains_only_token_digest() -> None:
    columns = Base.metadata.tables["admin_invitations"].columns

    assert "token_digest" in columns
    assert columns["token_digest"].type.length == 64
    assert "invitation_token" not in columns
