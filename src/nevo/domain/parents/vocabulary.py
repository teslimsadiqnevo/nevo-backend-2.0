from enum import StrEnum


class GrowthDimension(StrEnum):
    """The four things a parent is told about, and nothing else.

    Deliberately not achievement. None of these is a score, a rank, or a
    comparison against other children - they are ways of learning that a
    parent can recognise at home.
    """

    STAYING_WITH_HARD_PROBLEMS = "staying_with_hard_problems"
    KNOWING_WHAT_SHE_KNOWS = "knowing_what_she_knows"
    CONNECTING_IDEAS = "connecting_ideas"
    LEARNING_NEW_THINGS_FASTER = "learning_new_things_faster"


class GrowthTrend(StrEnum):
    """How a dimension is moving, as a closed set.

    ``not_enough_yet`` is the important one. A term with three lessons in it
    cannot support a judgement about a child, and saying so is better than
    manufacturing an encouraging sentence out of nothing - a parent who is
    told their child is growing on no evidence has been misled, however
    kindly.
    """

    GROWING = "growing"
    STEADY = "steady"
    EMERGING = "emerging"
    NOT_ENOUGH_YET = "not_enough_yet"
