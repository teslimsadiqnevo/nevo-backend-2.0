from sqlalchemy import CheckConstraint, Enum, Index, UniqueConstraint

from nevo.db import models  # noqa: F401
from nevo.db.base import Base


def test_scaffold_state_table_tracks_student_concept_level() -> None:
    table = Base.metadata.tables["student_concept_scaffold_states"]
    columns = table.columns

    assert {
        "student_id",
        "concept_id",
        "current_intensity",
        "consecutive_correct",
        "response_time_improvement_streak",
        "reduced_hint_streak",
        "last_response_time_ms",
        "last_hint_count",
    }.issubset(columns.keys())
    intensity = columns["current_intensity"]
    assert isinstance(intensity.type, Enum)
    assert intensity.type.enums == [
        "full_support",
        "partial_support",
        "hints_only",
        "independent",
    ]


def test_scaffold_state_is_unique_per_student_and_concept() -> None:
    table = Base.metadata.tables["student_concept_scaffold_states"]
    unique_sets = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    indexes = {
        index.name
        for index in table.indexes
        if isinstance(index, Index) and index.name
    }

    assert ("student_id", "concept_id") in unique_sets
    assert "ix_student_concept_scaffold_states_student_concept" in indexes


def test_scaffold_problem_logs_are_dashboard_visible_evidence() -> None:
    table = Base.metadata.tables["scaffold_problem_logs"]
    columns = table.columns

    assert {
        "student_id",
        "concept_id",
        "problem_id",
        "scaffold_intensity",
        "outcome",
        "hint_count",
        "next_scaffold_intensity",
        "level_changed",
        "change_reason",
    }.issubset(columns.keys())
    checks = {
        constraint.name or ""
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert any(name.endswith("scaffold_log_hint_count_nonnegative") for name in checks)
