from collections.abc import Iterable

from sqlalchemy import CheckConstraint, Enum, ForeignKeyConstraint, Index

from nevo.db import models  # noqa: F401
from nevo.db.base import Base


def enum_values(column_name: str) -> list[str]:
    column = Base.metadata.tables["teacher_class_assignments"].columns[
        column_name
    ]
    assert isinstance(column.type, Enum)
    return list(column.type.enums)


def foreign_key_targets() -> set[tuple[str, str]]:
    table = Base.metadata.tables["teacher_class_assignments"]
    targets: set[tuple[str, str]] = set()
    for constraint in table.constraints:
        if isinstance(constraint, ForeignKeyConstraint):
            for element in constraint.elements:
                targets.add((element.column.table.name, element.column.name))
    return targets


def check_names() -> Iterable[str]:
    for constraint in Base.metadata.tables[
        "teacher_class_assignments"
    ].constraints:
        if isinstance(constraint, CheckConstraint) and constraint.name:
            yield constraint.name


def index_names() -> set[str]:
    return {
        index.name
        for index in Base.metadata.tables[
            "teacher_class_assignments"
        ].indexes
        if isinstance(index, Index) and index.name
    }


def test_teacher_assignment_table_and_enums_exist() -> None:
    assert "teacher_class_assignments" in Base.metadata.tables
    assert enum_values("role") == ["primary", "co_teacher"]
    assert enum_values("source") == ["manual", "roster_sync"]


def test_assignment_references_tenant_teacher_class_and_history() -> None:
    targets = foreign_key_targets()
    assert ("schools", "id") in targets
    assert ("users", "id") in targets
    assert ("classes", "id") in targets
    assert ("teacher_class_assignments", "id") in targets


def test_active_assignment_invariants_are_indexed() -> None:
    indexes = index_names()
    assert "uq_teacher_class_assignments_active_pair" in indexes
    assert "uq_teacher_class_assignments_active_primary" in indexes


def test_removal_history_has_timestamp_check() -> None:
    assert (
        "ck_teacher_class_assignments_removed_after_assignment"
        in set(check_names())
    )
