"""Local Rasch (1PL IRT) probing with an EAP posterior and item information.

Bank difficulties are provisional item parameters, not population calibration.
Historical responses use the difficulty recorded at the time.
"""

from dataclasses import dataclass
from math import exp, log, sqrt

STARTING_DIFFICULTY = 0.5
MIN_QUESTIONS = 5
MAX_QUESTIONS = 8
THETA_GRID = tuple(-4 + index / 10 for index in range(81))
PRIOR = tuple(exp(-(theta**2) / (2 * 1.5**2)) for theta in THETA_GRID)
STARTING_STEP = (
    sqrt(sum(w * t * t for w, t in zip(PRIOR, THETA_GRID, strict=True)) / sum(PRIOR)) / 6
)


def _logit(value):
    value = min(0.99, max(0.01, value))
    return log(value / (1 - value))


def _probability(theta, difficulty):
    return 1 / (1 + exp(-(theta - _logit(difficulty))))


@dataclass(frozen=True)
class ProbeState:
    asked: int
    estimate: float
    step: float
    posterior: tuple[float, ...] = ()

    @property
    def finished(self):
        return self.asked >= MAX_QUESTIONS or (
            self.asked >= MIN_QUESTIONS and self.step * 6 <= 0.65
        )


def start():
    return ProbeState(
        0, STARTING_DIFFICULTY, STARTING_STEP, tuple(weight / sum(PRIOR) for weight in PRIOR)
    )


def after(state, *, correct, difficulty=None):
    difficulty = state.estimate if difficulty is None else difficulty
    weights = state.posterior or start().posterior
    posterior = tuple(
        weight * (probability if correct else 1 - probability)
        for weight, theta in zip(weights, THETA_GRID, strict=True)
        for probability in [_probability(theta, difficulty)]
    )
    total = sum(posterior)
    posterior = tuple(weight / total for weight in posterior)
    mean = sum(theta * weight for theta, weight in zip(THETA_GRID, posterior, strict=True))
    variance = sum(
        (theta - mean) ** 2 * weight for theta, weight in zip(THETA_GRID, posterior, strict=True)
    )
    return ProbeState(state.asked + 1, 1 / (1 + exp(-mean)), sqrt(variance) / 6, posterior)


def item_information(state, difficulty):
    return sum(
        weight * probability * (1 - probability)
        for theta, weight in zip(THETA_GRID, state.posterior or start().posterior, strict=True)
        for probability in [_probability(theta, difficulty)]
    )


def choose(state, *, available, already_asked):
    unseen = [(item, difficulty) for item, difficulty in available if item not in already_asked]
    if not unseen:
        return None
    return min(unseen, key=lambda pair: (-item_information(state, pair[1]), str(pair[0])))[0]


def entry_point(state):
    return min(0.85, max(0.15, state.estimate))


def recalibrate(difficulty, *, times_answered, times_correct):
    # Empirical ease is not fitted Rasch calibration; keep its provenance clear.
    if times_answered <= 0:
        return difficulty
    weight = times_answered / (times_answered + 20)
    return min(
        1.0,
        max(
            0.0, round(difficulty * (1 - weight) + (1 - times_correct / times_answered) * weight, 4)
        ),
    )
