from sqlalchemy import CheckConstraint, Enum, Index, UniqueConstraint

from nevo.db import models  # noqa: F401
from nevo.db.base import Base


def enum_values(table_name: str, column_name: str) -> list[str]:
    column = Base.metadata.tables[table_name].columns[column_name]
    assert isinstance(column.type, Enum)
    return list(column.type.enums)


def test_ai_gateway_tables_exist() -> None:
    assert "ai_prompt_templates" in Base.metadata.tables
    assert "ai_gateway_calls" in Base.metadata.tables


def test_prompt_templates_are_versioned_with_one_active_name() -> None:
    table = Base.metadata.tables["ai_prompt_templates"]
    unique_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    index_names = {
        index.name for index in table.indexes if isinstance(index, Index)
    }

    assert "uq_ai_prompt_templates_name_version" in unique_names
    assert "uq_ai_prompt_templates_active_name" in index_names


def test_gateway_call_enums_and_privacy_contract_are_exact() -> None:
    assert enum_values("ai_gateway_calls", "service") == [
        "adaptation",
        "lesson_generation",
        "narrative",
    ]
    assert enum_values("ai_gateway_calls", "status") == [
        "succeeded",
        "fallback",
        "failed",
    ]
    columns = Base.metadata.tables["ai_gateway_calls"].columns
    assert "prompt" not in columns
    assert "response" not in columns
    assert "estimated_cost_usd" in columns


def test_gateway_call_has_integrity_checks() -> None:
    names = {
        constraint.name
        for constraint in Base.metadata.tables["ai_gateway_calls"].constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "ck_ai_gateway_calls_token_counts_non_negative" in names
    assert "ck_ai_gateway_calls_performance_values_non_negative" in names
    assert "ck_ai_gateway_calls_fallback_status_matches_flag" in names
