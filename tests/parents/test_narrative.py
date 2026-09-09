"""The growth narrative: evidence in, prose out, and nothing numeric."""
import re

from nevo.domain.parents.vocabulary import GrowthDimension, GrowthTrend
from nevo.parents.entities import GrowthSignals
from nevo.parents.narrative import (
    MINIMUM_SESSIONS,
    compose,
    headline_and_summary,
)


def signals(**overrides: object) -> GrowthSignals:
    base: dict[str, object] = {
        "sessions": 20,
        "completed_sessions": 16,
        "exited_sessions": 4,
        "exit_attempts": 2,
        "self_adjustments": 12,
        "comprehension_responses": 30,
        "subjects_touched": 3,
        "concepts_practised": 20,
        "concepts_confident": 10,
        "practice_per_confident_concept": 3.0,
    }
    base.update(overrides)
    return GrowthSignals(**base)  # type: ignore[arg-type]


def test_every_dimension_is_answered_exactly_once() -> None:
    statements = compose(name="Amara", current=signals(), previous=signals())

    assert [item.dimension for item in statements] == list(GrowthDimension)


def test_no_statement_contains_a_number_or_a_percentage() -> None:
    """The screen is defined by what it must not say."""
    for current, previous in (
        (signals(), signals()),
        (signals(sessions=2), signals()),
        (signals(completed_sessions=20), signals(completed_sessions=4)),
        (signals(subjects_touched=1), signals()),
    ):
        for item in compose(name="Amara", current=current, previous=previous):
            assert not re.search(r"\d", item.statement), item.statement
            assert "%" not in item.statement


def test_a_child_with_barely_any_lessons_gets_no_judgement() -> None:
    statements = compose(
        name="Amara",
        current=signals(sessions=MINIMUM_SESSIONS - 1),
        previous=signals(),
    )

    assert {item.trend for item in statements} == {GrowthTrend.NOT_ENOUGH_YET}
    for item in statements:
        assert "not been enough" in item.statement or "not worked across" in item.statement


def test_a_first_term_is_emerging_rather_than_growing() -> None:
    """Nothing to grow against, so claiming growth would be inventing it."""
    statements = compose(
        name="Amara",
        current=signals(),
        previous=signals(sessions=0, completed_sessions=0, concepts_confident=0),
    )

    assert GrowthTrend.GROWING not in {item.trend for item in statements}


def test_finishing_more_lessons_reads_as_staying_with_hard_problems() -> None:
    statements = compose(
        name="Amara",
        current=signals(sessions=20, completed_sessions=18),
        previous=signals(sessions=20, completed_sessions=10),
    )
    persistence = next(
        item
        for item in statements
        if item.dimension is GrowthDimension.STAYING_WITH_HARD_PROBLEMS
    )

    assert persistence.trend is GrowthTrend.GROWING
    assert "tricky questions" in persistence.statement


def test_fewer_attempts_per_idea_reads_as_learning_faster() -> None:
    statements = compose(
        name="Amara",
        current=signals(practice_per_confident_concept=2.0),
        previous=signals(practice_per_confident_concept=6.0),
    )
    speed = next(
        item
        for item in statements
        if item.dimension is GrowthDimension.LEARNING_NEW_THINGS_FASTER
    )

    assert speed.trend is GrowthTrend.GROWING
    assert "landing more quickly" in speed.statement


def test_one_subject_is_not_a_connection() -> None:
    statements = compose(
        name="Amara",
        current=signals(subjects_touched=1),
        previous=signals(subjects_touched=1),
    )
    connecting = next(
        item for item in statements if item.dimension is GrowthDimension.CONNECTING_IDEAS
    )

    assert connecting.trend is GrowthTrend.NOT_ENOUGH_YET


def test_the_child_is_named_and_never_gendered() -> None:
    statements = compose(name="Amara", current=signals(), previous=signals())
    prose = " ".join(item.statement for item in statements)

    assert "Amara" in prose
    # The roster holds no pronoun, and guessing one misgenders a real child.
    assert not re.search(r"\b(her|his|she|he)\b", prose)


def test_a_term_with_nothing_in_it_says_so_rather_than_encouraging() -> None:
    statements = compose(
        name="Amara", current=signals(sessions=0), previous=signals(sessions=0)
    )
    headline, summary = headline_and_summary(name="Amara", statements=statements)

    assert "not had enough lessons" in summary
    assert "growing" not in headline.lower()


def test_a_nameless_child_reads_correctly_at_the_start_and_the_middle() -> None:
    """The fallback is lower case so it works mid-sentence, and lifted at the
    start of one. A live run produced "How Your child is getting on"."""
    statements = compose(name="your child", current=signals(), previous=signals())
    prose = [item.statement for item in statements]

    for statement in prose:
        assert statement[0].isupper(), statement
        assert "Your child" not in statement[1:], statement

    headline, summary = headline_and_summary(name="your child", statements=statements)
    assert "Your child" not in headline
    assert headline.startswith("How your child")
    assert summary[0].isupper()


def test_no_statement_disagrees_with_itself_grammatically() -> None:
    """A live run produced "what their has understood"."""
    for current, previous in (
        (signals(), signals()),
        (signals(sessions=1), signals()),
        (signals(), signals(sessions=0, concepts_confident=0)),
        (signals(completed_sessions=20), signals(completed_sessions=4)),
    ):
        for name in ("Amara", "your child"):
            for item in compose(name=name, current=current, previous=previous):
                assert " their has " not in item.statement
                assert " their is " not in item.statement
                assert not re.search(r"\b(their|they)\s+(has|is|was)\b", item.statement)
