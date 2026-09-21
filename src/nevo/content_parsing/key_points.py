"""How sure we are that a key point came from the lesson it is attached to.

The review screen asks a teacher to check the parts Nevo was unsure it read
correctly. Nothing in the pipeline produced an "unsure", so there was nothing
to show: the model was never asked for a confidence, and a score a model
volunteers about its own output is not evidence anyway.

So it is measured instead. A key point drawn from a paragraph repeats that
paragraph's words. One the model inferred, generalised or invented does not,
and that is exactly the one a teacher should read. The number is the share of
the key point's own content words that appear in the text it was drawn from,
which is explainable to a teacher in one sentence and costs nothing to compute.
"""

from __future__ import annotations

import re

from nevo.domain.intelligence.vocabulary import KeyPointConfidence

#: Words that say nothing about where a sentence came from. Matching on them
#: would ground every key point against every paragraph.
STOP_WORDS = frozenset(
    """
    a an and are as at be been being but by can could did do does for from had
    has have how if in into is it its may might must not of on or our over
    should so some such than that the their them then there these they this
    those to up was were what when where which while who why will with would
    you your
    """.split()
)

#: At or above this share of grounded words, a key point stands without review.
SETTLED_GROUNDING = 0.8

#: Below this, a teacher is asked to look.
UNSURE_GROUNDING = 0.6

WORD = re.compile(r"[a-z0-9]+")


def content_words(text: str) -> list[str]:
    return [word for word in WORD.findall(text.casefold()) if word not in STOP_WORDS]


def grounding(point: str, source: str) -> float:
    """The share of the key point's content words present in the source.

    A point with nothing but stop words in it cannot be grounded either way;
    it is treated as ungrounded, because a key point that says nothing is
    exactly what a teacher should be shown.
    """

    words = content_words(point)
    if not words:
        return 0.0
    available = set(content_words(source))
    return sum(1 for word in words if word in available) / len(words)


def confidence(point: str, source: str) -> KeyPointConfidence:
    score = grounding(point, source)
    if score >= SETTLED_GROUNDING:
        return KeyPointConfidence.HIGH
    if score >= UNSURE_GROUNDING:
        return KeyPointConfidence.MEDIUM
    return KeyPointConfidence.LOW
