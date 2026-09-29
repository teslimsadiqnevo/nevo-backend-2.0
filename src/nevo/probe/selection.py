"""Choosing the next probe item, and what the probe concluded.

A right answer serves a harder item, a wrong one serves an easier item, and the
run converges in roughly five to eight questions. The output is the entry point
into that subject's knowledge graph - the starting mastery estimate the rest of
the model builds on - which is the only thing the probe exists to produce.

Deliberately not an IRT implementation. A binary search over difficulty with a
shrinking step converges in the same handful of questions for a bank of sixteen
items, is explainable to a teacher in one sentence, and does not pretend to a
precision that sixteen items cannot support. When the bank is large enough for
the estimate to deserve better, this is the one file that changes.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Where a run starts, knowing nothing. The middle.
STARTING_DIFFICULTY = 0.5

#: The first move's size. Halved after every answer, so the run narrows rather
#: than oscillating: 0.25, 0.125, 0.0625 and so on.
STARTING_STEP = 0.25

#: Fewer than this and the estimate rests on too little. More and a child is
#: being tested rather than placed - the probe is a starting point, not an exam.
MIN_QUESTIONS = 5
MAX_QUESTIONS = 8

#: How far from the target an item can sit and still be the best available. A
#: bank of sixteen will not hold something at exactly 0.6875.
NEAREST_ENOUGH = 1.0


@dataclass(frozen=True, slots=True)
class ProbeState:
    """Where a run has got to, derived from the answers so far.

    Held as a value rather than a row: the answers are the record, and a
    resumed probe recomputes from them. That way a run interrupted by a flat
    battery picks up exactly where it was rather than starting again.
    """

    asked: int
    estimate: float
    step: float

    @property
    def finished(self) -> bool:
        """Whether the probe has enough to place the child.

        It stops early once the step is smaller than the bank can distinguish:
        asking a sixth question that cannot move the answer wastes a child's
        attention.
        """

        if self.asked >= MAX_QUESTIONS:
            return True
        return self.asked >= MIN_QUESTIONS and self.step < 0.05


def start() -> ProbeState:
    return ProbeState(asked=0, estimate=STARTING_DIFFICULTY, step=STARTING_STEP)


def after(state: ProbeState, *, correct: bool) -> ProbeState:
    """Where the probe moves once the child has answered.

    Right goes harder, wrong goes easier, and the step halves either way. The
    estimate is clamped rather than allowed off the end, because an estimate of
    1.1 is not a stronger claim than 1.0 - it is a broken one.
    """

    direction = 1 if correct else -1
    estimate = min(1.0, max(0.0, state.estimate + direction * state.step))
    return ProbeState(asked=state.asked + 1, estimate=estimate, step=state.step / 2)


def choose(
    state: ProbeState,
    *,
    available: list[tuple[object, float]],
    already_asked: set[object],
) -> object | None:
    """The item closest to where the probe currently thinks the child is.

    Nothing is asked twice in one run: a repeat measures the child's memory of
    the last minute rather than what they know, and children notice.
    """

    unseen = [
        (item_id, difficulty) for item_id, difficulty in available if item_id not in already_asked
    ]
    if not unseen:
        return None
    best = min(unseen, key=lambda pair: (abs(pair[1] - state.estimate), str(pair[0])))
    return best[0] if abs(best[1] - state.estimate) <= NEAREST_ENOUGH else None


def entry_point(state: ProbeState) -> float:
    """The starting mastery estimate for this subject's knowledge graph.

    The probe's whole output. Bounded well away from certainty at both ends: a
    child who answered five questions has not proved they know everything, and
    seeding a graph at 1.0 means nothing can ever be taught to them.
    """

    return min(0.85, max(0.15, state.estimate))


def recalibrate(difficulty: float, *, times_answered: int, times_correct: int) -> float:
    """Move an item's difficulty towards what children actually did with it.

    Difficulty is learned rather than assigned. An item everybody gets right is
    easier than whoever wrote it thought. The move is weighted by how many
    answers it rests on, so one lucky run does not rewrite an item that four
    hundred children have already sat.
    """

    if times_answered <= 0:
        return difficulty
    observed_ease = times_correct / times_answered
    # An item answered correctly 80% of the time is a 0.2-difficulty item.
    observed_difficulty = 1.0 - observed_ease
    # Confidence grows with answers and never reaches 1, so the written
    # estimate always retains some weight.
    weight = times_answered / (times_answered + 20)
    blended = difficulty * (1 - weight) + observed_difficulty * weight
    return min(1.0, max(0.0, round(blended, 4)))
