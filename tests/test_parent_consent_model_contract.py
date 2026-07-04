from sqlalchemy import CheckConstraint, Enum, ForeignKeyConstraint, UniqueConstraint

from nevo.db import models  # noqa: F401
from nevo.db.base import Base


def enum_values(table_name: str, column_name: str) -> list[str]:
    column = Base.metadata.tables[table_name].columns[column_name]
    assert isinstance(column.type, Enum)
    return list(column.type.enums)


def foreign_key_targets(table_name: str) -> set[tuple[str, str]]:
    targets: set[tuple[str, str]] = set()
    for constraint in Base.metadata.tables[table_name].constraints:
        if isinstance(constraint, ForeignKeyConstraint):
            for element in constraint.elements:
                targets.add((element.column.table.name, element.column.name))
    return targets


def constraint_names(
    table_name: str,
    constraint_type: type[CheckConstraint] | type[UniqueConstraint],
) -> set[str]:
    return {
        constraint.name
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, constraint_type)
        and constraint.name is not None
    }


def test_parent_consent_tables_exist() -> None:
    for table_name in (
        "parent_links",
        "consent_invitations",
        "consent_invitation_items",
        "consent_notification_outbox",
    ):
        assert table_name in Base.metadata.tables


def test_parent_link_contract_is_school_and_user_scoped() -> None:
    targets = foreign_key_targets("parent_links")
    assert ("schools", "id") in targets
    assert ("users", "id") in targets
    assert "uq_parent_links_student_contact_method" in constraint_names(
        "parent_links",
        UniqueConstraint,
    )
    assert "ck_parent_links_account_created_matches_parent" in constraint_names(
        "parent_links",
        CheckConstraint,
    )


def test_parent_contact_and_delivery_enums_are_exact() -> None:
    assert enum_values("parent_links", "contact_method") == ["email", "sms"]
    assert enum_values("consent_notification_outbox", "status") == [
        "queued",
        "sent",
        "failed",
    ]


def test_consent_record_distinguishes_confirmation_source() -> None:
    assert enum_values("consent_records", "confirmation_source") == [
        "school",
        "parent",
    ]
    assert ("users", "id") in foreign_key_targets("consent_records")
    assert (
        "ck_consent_records_confirmation_fields_match_status"
        in constraint_names("consent_records", CheckConstraint)
    )
