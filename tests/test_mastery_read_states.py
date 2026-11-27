"""S21: the rules that turn the engine's evidence into level and reading states."""

from types import SimpleNamespace

from nevo.domain.mastery.vocabulary import FailureAttribution
from nevo.mastery import read


def _level(probability=0.15, *, practice=1, independent=0, supported=0):
    return SimpleNamespace(
        mastery_probability=probability,
        practice_count=practice,
        independent_pass_count=independent,
        supported_pass_count=supported,
    )


def _reading(probability=0.8, *, practice=1, attribution=FailureAttribution.NONE):
    return SimpleNamespace(
        mastery_probability_reading=probability,
        practice_count=practice,
        last_failure_attribution=attribution,
    )


def test_nothing_observed_is_absent_not_not() -> None:
    assert read.level_state(None) is None
    assert read.level_state(_level(practice=0)) is None


def test_reached_is_the_engines_own_rule() -> None:
    assert read.level_state(_level(0.82, independent=2, practice=3)) == "reached"
    # High probability on one unsupported pass is not yet reached.
    assert read.level_state(_level(0.9, independent=1, practice=2)) == "working"
    # Two passes and a low estimate is not reached either.
    assert read.level_state(_level(0.5, independent=2, practice=4)) == "working"


def test_working_needs_a_pass_and_not_has_none() -> None:
    assert read.level_state(_level(0.3, supported=1, practice=2)) == "working"
    assert read.level_state(_level(0.3, practice=3)) == "not"


def test_the_climb_stops_at_a_gap() -> None:
    levels = {"knowing_and_understanding": "working", "application": "reached"}
    assert read.highest_reached(levels) is None
    assert read.next_level(None) == "knowing_and_understanding"
    assert read.next_level("analysis_and_evaluation") is None


def test_reading_states() -> None:
    assert read.reading_state(None) is None
    assert read.reading_state(_reading(practice=0)) is None
    assert read.reading_state(_reading(0.8)) == "at"
    assert read.reading_state(_reading(0.5)) == "support"
    assert read.reading_state(_reading(0.8, attribution=FailureAttribution.READING)) == "support"
    # Met only in material that asks for very little reading.
    assert read.reading_state(_reading(0.5), max_text_density=0.1) == "none"
    assert read.reading_state(_reading(0.8), max_text_density=0.7) == "at"


def test_the_engine_word_knowledge_never_leaves() -> None:
    assert read.LEVELS == (
        "knowing_and_understanding",
        "application",
        "analysis_and_evaluation",
    )
    assert read.level_from_engine("knowledge") == "knowing_and_understanding"
    assert read.level_from_engine("analysis") == "analysis_and_evaluation"
