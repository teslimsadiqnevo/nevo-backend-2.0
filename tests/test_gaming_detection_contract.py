import inspect

import pytest
from sqlalchemy import CheckConstraint, Enum, Index

from nevo.db import models  # noqa: F401
from nevo.db.base import Base
from nevo.domain.learner_profiles import gaming_rules
from nevo.domain.learner_profiles.gaming_rules import (
    GAMING_THRESHOLD_RULES,
    GAMING_THRESHOLD_RULES_BY_KEY,
    SURFACEABLE_SUSPICION_LEVELS,
    TEACHER_NOTIFICATION_TEMPLATES,
)
from nevo.domain.learner_profiles.vocabulary import (
    CANONICAL_PROFILE_DIMENSIONS,
    EngagementAnomalyScope,
    GamingSuspicionLevel,
)


def check_names(table_name: str) -> set[str]:
    return {
        constraint.name or ""
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, CheckConstraint)
    }


def index_names(table_name: str) -> set[str]:
    return {
        index.name
        for index in Base.metadata.tables[table_name].indexes
        if isinstance(index, Index) and index.name
    }


def test_profile_carries_stored_gaming_suspicion_fields() -> None:
    columns = Base.metadata.tables["learner_profiles"].columns

    level = columns["gaming_suspicion_level"]
    assert isinstance(level.type, Enum)
    assert level.type.enums == ["none", "low", "moderate", "high"]
    assert level.nullable is False
    assert columns["gaming_suspicion_updated_at"].nullable is True
    assert columns["gaming_anomaly_count"].nullable is False


def test_gaming_suspicion_is_not_a_learning_dimension() -> None:
    """It must never join the inference dimension set or reach history."""
    assert "gaming_suspicion_level" not in CANONICAL_PROFILE_DIMENSIONS
    history = Base.metadata.tables["learner_profile_history"].columns
    assert "gaming_suspicion_level" not in history


def test_profile_gaming_invariants_are_enforced_in_the_database() -> None:
    names = check_names("learner_profiles")
    assert any(
        name.endswith("gaming_anomaly_count_nonnegative") for name in names
    )
    assert any(
        name.endswith("gaming_suspicion_level_matches_timestamp")
        for name in names
    )


def test_anomaly_ledger_records_evidence_with_its_rule() -> None:
    columns = Base.metadata.tables["learner_engagement_anomalies"].columns

    assert columns["rule_key"].nullable is False
    assert columns["baseline_value"].nullable is False
    assert columns["observed_value"].nullable is False
    assert columns["deviation_ratio"].nullable is False
    assert columns["distinct_content_types"].nullable is False
    # A session may be pruned without destroying the evidence trail.
    assert columns["lesson_session_id"].nullable is True

    scope = columns["scope"]
    assert isinstance(scope.type, Enum)
    assert scope.type.enums == ["single_content_type", "all_content_types"]


def test_anomaly_ledger_is_indexed_for_its_read_paths() -> None:
    indexes = index_names("learner_engagement_anomalies")
    assert "ix_learner_engagement_anomalies_student_detected" in indexes
    assert "ix_learner_engagement_anomalies_rule_detected" in indexes


def test_every_rule_requires_breadth_across_content_types() -> None:
    """Breadth is the discriminator between struggling and steering."""
    for rule in GAMING_THRESHOLD_RULES:
        assert rule.scope is EngagementAnomalyScope.ALL_CONTENT_TYPES
        assert rule.minimum_distinct_content_types >= 3
        assert rule.minimum_deviation_ratio >= 2.0
        assert rule.minimum_observations >= 1
        assert rule.sustained_over_sessions >= 2


def test_rule_keys_are_unique_and_addressable() -> None:
    keys = [rule.key for rule in GAMING_THRESHOLD_RULES]
    assert len(keys) == len(set(keys))
    assert set(GAMING_THRESHOLD_RULES_BY_KEY) == set(keys)


def test_weak_signals_cannot_reach_the_highest_level_alone() -> None:
    """Errors and abandonment look identical to disengagement."""
    for key in ("errors_spike_against_mastery", "abandoned_attempts_spike"):
        assert (
            GAMING_THRESHOLD_RULES_BY_KEY[key].suspicion_level
            is GamingSuspicionLevel.LOW
        )


def test_higher_levels_demand_stronger_evidence() -> None:
    doubled = GAMING_THRESHOLD_RULES_BY_KEY["response_time_doubled_everywhere"]
    tripled = GAMING_THRESHOLD_RULES_BY_KEY["response_time_tripled_everywhere"]

    assert tripled.minimum_deviation_ratio > doubled.minimum_deviation_ratio
    assert tripled.sustained_over_sessions > doubled.sustained_over_sessions
    assert tripled.suspicion_level is GamingSuspicionLevel.HIGH


def test_teacher_copy_never_accuses_the_student() -> None:
    accusatory = (
        "gaming",
        "cheat",
        "manipulat",
        "dishonest",
        "lying",
        "faking",
        "pretend",
        "deliberate",
        "intentional",
        "suspicion",
        "suspect",
        "abuse",
    )
    for level, template in TEACHER_NOTIFICATION_TEMPLATES.items():
        normalized = template.casefold()
        for term in accusatory:
            assert term not in normalized, (level, term)
        assert "{student_name}" in template


def test_nothing_surfaces_when_no_suspicion_is_held() -> None:
    assert GamingSuspicionLevel.NONE not in TEACHER_NOTIFICATION_TEMPLATES
    assert GamingSuspicionLevel.NONE not in SURFACEABLE_SUSPICION_LEVELS
    assert SURFACEABLE_SUSPICION_LEVELS == {
        GamingSuspicionLevel.LOW,
        GamingSuspicionLevel.MODERATE,
        GamingSuspicionLevel.HIGH,
    }


def test_rules_module_stays_declarative() -> None:
    """SCRUM-62 is schema and rules only: no detection logic ships yet."""
    functions = [
        name
        for name, value in vars(gaming_rules).items()
        # Python 3.14 adds a module-level __annotate__ (PEP 649).
        if not name.startswith("__")
        and inspect.isfunction(value)
        and value.__module__ == gaming_rules.__name__
    ]
    assert functions == []


def test_rule_tables_are_immutable() -> None:
    assert isinstance(GAMING_THRESHOLD_RULES, tuple)
    for mapping in (GAMING_THRESHOLD_RULES_BY_KEY, TEACHER_NOTIFICATION_TEMPLATES):
        with pytest.raises(TypeError):
            mapping["x"] = "y"  # type: ignore[index]
