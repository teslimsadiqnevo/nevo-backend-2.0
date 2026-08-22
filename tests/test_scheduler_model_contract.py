from sqlalchemy import CheckConstraint, Index, UniqueConstraint

from nevo.db import models  # noqa: F401
from nevo.db.base import Base


def test_student_concept_scheduling_table_matches_fsrs_contract() -> None:
    table = Base.metadata.tables["student_concept_scheduling"]
    columns = table.columns

    assert {
        "student_id",
        "concept_id",
        "stability",
        "difficulty",
        "last_review",
        "review_count",
        "next_review_due",
    }.issubset(columns.keys())


def test_student_concept_scheduling_constraints_and_indexes() -> None:
    table = Base.metadata.tables["student_concept_scheduling"]
    checks = {
        constraint.name or ""
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    indexes = {
        index.name
        for index in table.indexes
        if isinstance(index, Index) and index.name
    }
    unique_sets = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert any(name.endswith("scheduling_stability_positive") for name in checks)
    assert any(name.endswith("scheduling_difficulty_range") for name in checks)
    assert any(name.endswith("scheduling_review_count_nonnegative") for name in checks)
    assert ("student_id", "concept_id") in unique_sets
    assert "ix_student_concept_scheduling_student_due" in indexes
