"""The adaptive probe. SCRUM-175.

It was specified as adaptive and was not one: sixteen items hardcoded in the
front end with a local answer key, no difficulty attached and no adaptation
possible. An answer key on the device also measures a child's willingness to
read the source rather than what they know.
"""

from __future__ import annotations

import inspect

import pytest

from nevo.probe.selection import (
    MAX_QUESTIONS,
    MIN_QUESTIONS,
    after,
    choose,
    entry_point,
    recalibrate,
    start,
)


def run(answers: list[bool]):
    state = start()
    for correct in answers:
        state = after(state, correct=correct)
    return state


def test_a_right_answer_goes_harder_and_a_wrong_one_goes_easier() -> None:
    assert after(start(), correct=True).estimate > start().estimate
    assert after(start(), correct=False).estimate < start().estimate


def test_the_step_halves_so_the_run_narrows_rather_than_oscillating() -> None:
    first = after(start(), correct=True)
    second = after(first, correct=False)

    assert second.step < first.step < start().step


def test_it_converges_in_five_to_eight_questions() -> None:
    """A probe is a placement, not an exam."""

    state = start()
    asked = 0
    while not state.finished and asked < 20:
        state = after(state, correct=asked % 2 == 0)
        asked += 1

    assert MIN_QUESTIONS <= asked <= MAX_QUESTIONS


def test_a_child_who_gets_everything_right_still_stops() -> None:
    state = run([True] * MAX_QUESTIONS)

    assert state.finished


@pytest.mark.parametrize("answers", [[True] * 8, [False] * 8])
def test_the_estimate_never_runs_off_the_end(answers: list[bool]) -> None:
    """An estimate of 1.1 is not a stronger claim, it is a broken one."""

    state = run(answers)

    assert 0.0 <= state.estimate <= 1.0


def test_the_entry_point_is_bounded_away_from_certainty() -> None:
    """Seeding a graph at 1.0 means nothing can ever be taught to the child."""

    assert entry_point(run([True] * 8)) <= 0.85
    assert entry_point(run([False] * 8)) >= 0.15


def test_the_next_item_is_the_one_nearest_the_current_estimate() -> None:
    state = after(start(), correct=True)  # estimate 0.75

    chosen = choose(
        state,
        available=[("easy", 0.1), ("middle", 0.5), ("hard", 0.8)],
        already_asked=set(),
    )

    assert chosen == "hard"


def test_nothing_is_asked_twice_in_one_run() -> None:
    """A repeat measures a child's memory of the last minute."""

    state = start()

    chosen = choose(
        state,
        available=[("a", 0.5), ("b", 0.55)],
        already_asked={"a"},
    )

    assert chosen == "b"
    assert choose(state, available=[("a", 0.5)], already_asked={"a"}) is None


def test_an_empty_bank_chooses_nothing() -> None:
    assert choose(start(), available=[], already_asked=set()) is None


def test_difficulty_moves_towards_what_children_actually_did() -> None:
    """Learned rather than assigned: an item everybody gets right is easy."""

    easier = recalibrate(0.5, times_answered=100, times_correct=90)
    harder = recalibrate(0.5, times_answered=100, times_correct=10)

    assert easier < 0.5 < harder


def test_one_run_cannot_rewrite_a_well_sat_item() -> None:
    from_one = recalibrate(0.5, times_answered=1, times_correct=1)
    from_many = recalibrate(0.5, times_answered=400, times_correct=400)

    # Both move towards easier, but one answer barely moves it.
    assert abs(from_one - 0.5) < abs(from_many - 0.5)
    assert abs(from_one - 0.5) < 0.05


def test_an_item_nobody_has_answered_keeps_its_written_estimate() -> None:
    assert recalibrate(0.42, times_answered=0, times_correct=0) == 0.42


def test_the_answer_key_never_reaches_the_device() -> None:
    from nevo.api.probe import ProbeQuestion

    fields = set(ProbeQuestion.model_fields)

    assert "correct_option" not in fields
    assert not any("answer" in field for field in fields)
    assert not any("correct" in field for field in fields)


def test_the_child_is_not_told_whether_they_were_right() -> None:
    """Telling them partway through changes how they answer the rest."""

    from nevo.api.probe import ProbeFinished, submit_answer

    source = inspect.getsource(submit_answer)

    assert "correct" not in set(ProbeFinished.model_fields)
    # It hands back the next question rather than a verdict.
    assert "next_question(" in source


def test_a_subject_with_no_items_says_so_cleanly() -> None:
    """Items come from uploaded lessons, so a fresh subject has none."""

    from nevo.api.probe import ProbeEmpty

    assert "no_items" in ProbeEmpty.model_fields
    assert ProbeEmpty.model_fields["finished"].default is True


def test_the_run_is_recomputed_from_the_answers_not_stored() -> None:
    """A run interrupted by a flat battery picks up where it was."""

    from nevo.api.probe import _state

    source = inspect.getsource(_state)

    assert "ProbeResponse" in source
    assert "order_by" in source


def test_an_item_records_where_it_came_from_and_what_it_is_worth() -> None:
    import nevo.db.models  # noqa: F401
    from nevo.db.base import Base

    columns = Base.metadata.tables["probe_items"].columns

    # Traceable back to the teaching it was generated from.
    for column in ("concept_id", "lesson_id", "band", "difficulty", "school_subject_id"):
        assert column in columns
    # Scoped to the school: one school's items never serve another's children.
    assert "school_id" in columns


def test_a_response_keeps_the_difficulty_it_was_served_at() -> None:
    import nevo.db.models  # noqa: F401
    from nevo.db.base import Base

    columns = Base.metadata.tables["probe_responses"].columns

    # A later recalibration must not rewrite what this child was actually asked.
    assert "difficulty_at_the_time" in columns
