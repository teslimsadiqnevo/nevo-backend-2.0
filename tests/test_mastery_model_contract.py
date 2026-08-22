from sqlalchemy import CheckConstraint, Enum, Index, UniqueConstraint

from nevo.db import models  # noqa: F401
from nevo.db.base import Base


def test_student_concept_mastery_table_matches_ticket_contract() -> None:
    table = Base.metadata.tables["student_concept_mastery"]
    columns = table.columns

    assert {
        "student_id",
        "concept_id",
        "mastery_probability_concept",
        "mastery_probability_reading",
        "attention_weights",
        "practice_count",
        "last_updated",
        "last_response_correct",
        "last_failure_attribution",
    }.issubset(set(columns.keys()))

    attribution = columns["last_failure_attribution"]
    assert isinstance(attribution.type, Enum)
    assert attribution.type.enums == ["concept", "reading", "mixed", "none"]


def test_mastery_table_is_indexed_by_student_and_concept() -> None:
    table = Base.metadata.tables["student_concept_mastery"]
    indexes = {
        index.name
        for index in table.indexes
        if isinstance(index, Index) and index.name
    }
    assert "ix_student_concept_mastery_student" in indexes
    assert "ix_student_concept_mastery_concept" in indexes
    assert "ix_student_concept_mastery_student_concept" in indexes

    unique_sets = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("student_id", "concept_id") in unique_sets


def test_mastery_probabilities_are_bounded_in_schema() -> None:
    checks = {
        constraint.name or ""
        for constraint in Base.metadata.tables[
            "student_concept_mastery"
        ].constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert any(name.endswith("mastery_probability_concept_range") for name in checks)
    assert any(name.endswith("mastery_probability_reading_range") for name in checks)
    assert any(name.endswith("guess_probability_range") for name in checks)
    assert any(name.endswith("slip_probability_range") for name in checks)
