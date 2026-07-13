from sqlalchemy import Enum, ForeignKeyConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB

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


def index_column_sets(table_name: str) -> dict[str, tuple[str, ...]]:
    return {
        index.name or "": tuple(column.name for column in index.columns)
        for index in Base.metadata.tables[table_name].indexes
        if isinstance(index, Index)
    }


def test_signal_events_table_exists_with_required_columns() -> None:
    table = Base.metadata.tables["signal_events"]

    assert set(table.columns.keys()) == {
        "id",
        "student_id",
        "session_id",
        "event_type",
        "event_data",
        "timestamp",
    }
    assert isinstance(table.columns["event_data"].type, JSONB)


def test_signal_event_type_enum_is_exact() -> None:
    assert enum_values("signal_events", "event_type") == [
        "time_on_segment",
        "replay",
        "scroll",
        "simplify_trigger",
        "expand_trigger",
        "slower_trigger",
        "comprehension_response",
        "exit_attempt",
        "break_suggested",
        "break_taken",
        "engagement_signal",
    ]


def test_signal_events_are_student_scoped() -> None:
    assert ("users", "id") in foreign_key_targets("signal_events")


def test_signal_event_query_indexes_match_ticket_contract() -> None:
    indexes = index_column_sets("signal_events")

    assert indexes["ix_signal_events_student_session"] == (
        "student_id",
        "session_id",
    )
    assert indexes["ix_signal_events_student_timestamp"] == (
        "student_id",
        "timestamp",
    )
    assert indexes["ix_signal_events_type_timestamp"] == (
        "event_type",
        "timestamp",
    )
