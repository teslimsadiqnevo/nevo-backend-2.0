from collections.abc import Iterable

from sqlalchemy import CheckConstraint, Enum, UniqueConstraint

from nevo.db import models  # noqa: F401
from nevo.db.base import Base
from nevo.domain.learner_profiles.vocabulary import (
    CANONICAL_PROFILE_DIMENSIONS,
    PROHIBITED_SCHEMA_TERMS,
)


def schema_tokens() -> Iterable[str]:
    for table in Base.metadata.sorted_tables:
        yield table.name

        for column in table.columns:
            yield column.name
            if isinstance(column.type, Enum):
                yield column.type.name
                yield from column.type.enums

        for constraint in table.constraints:
            if constraint.name:
                yield constraint.name

        for index in table.indexes:
            if index.name:
                yield index.name


def test_schema_uses_only_functional_vocabulary() -> None:
    violations: list[tuple[str, str]] = []

    for token in schema_tokens():
        normalized = token.casefold()
        for prohibited_term in PROHIBITED_SCHEMA_TERMS:
            if prohibited_term in normalized:
                violations.append((token, prohibited_term))

    assert violations == []


def test_current_profile_contains_all_canonical_dimensions() -> None:
    table = Base.metadata.tables["learner_profiles"]

    for dimension in CANONICAL_PROFILE_DIMENSIONS:
        assert dimension in table.columns
        assert f"{dimension}_confidence" in table.columns


def test_history_contains_all_canonical_dimensions() -> None:
    table = Base.metadata.tables["learner_profile_history"]

    for dimension in CANONICAL_PROFILE_DIMENSIONS:
        assert dimension in table.columns
        assert f"{dimension}_confidence" in table.columns


def test_every_confidence_column_uses_the_shared_enum() -> None:
    for table_name in ("learner_profiles", "learner_profile_history"):
        table = Base.metadata.tables[table_name]
        for dimension in CANONICAL_PROFILE_DIMENSIONS:
            column = table.columns[f"{dimension}_confidence"]
            assert isinstance(column.type, Enum)
            assert column.type.name == "profile_confidence"
            assert column.type.enums == ["low", "medium", "high"]


def test_current_profile_is_unique_per_learner() -> None:
    table = Base.metadata.tables["learner_profiles"]
    unique_column_sets = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("learner_id",) in unique_column_sets


def test_history_is_unique_per_profile_version() -> None:
    table = Base.metadata.tables["learner_profile_history"]
    unique_column_sets = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("learner_profile_id", "version") in unique_column_sets


def test_numeric_dimensions_have_database_checks() -> None:
    required_suffixes = {
        "cognitive_load_threshold_range",
        "processing_speed_range",
        "working_memory_capacity_range",
        "attention_span_range",
        "performance_sensitivity_range",
    }

    for table_name in ("learner_profiles", "learner_profile_history"):
        table = Base.metadata.tables[table_name]
        check_names = {
            constraint.name or ""
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        for suffix in required_suffixes:
            assert any(name.endswith(suffix) for name in check_names)
