"""Whether what a child typed counts as the answer.

There is no symbolic engine here, no per-subject checker, and no maths in the
front end. At upload the pipeline emits, for each step, every form that counts
as correct: one half, 0.5 and 50 percent are all stored; x+1 and 1+x are both
stored; 5 m/s with and without the space. At runtime the child's entry is
matched against that stored list.

That is why it works for every subject. The acceptable answers were generated
from that lesson, by something that had the lesson in front of it, rather than
by a checker that has to understand chemistry and Yoruba and long division.

What is left here is the matching, and it is deliberately dull: normalise both
sides the same way and compare. Anything cleverer starts to be a symbolic
engine, and a symbolic engine that is wrong about one subject is worse than a
list that is right about all of them.
"""

from __future__ import annotations

import re
import unicodedata

#: Characters a child's keyboard or a textbook produces that mean the same as
#: ours. Written as escapes rather than literals so nobody has to guess whether
#: a hyphen in the source is a hyphen.
SUBSTITUTIONS = {
    "\u2212": "-",  # minus sign
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u00d7": "*",  # multiplication sign
    "\u00f7": "/",  # division sign
    "\u2044": "/",  # fraction slash
    "\u201c": '"',  # left double quote
    "\u201d": '"',  # right double quote
    "\u2018": "'",  # left single quote
    "\u2019": "'",  # right single quote, which is also an apostrophe
}

#: Trailing punctuation a child adds and a teacher would not mark down.
TRAILING = ".,;:!?"

#: Spacing around an operator is typing, not meaning: a child who writes
#: "x + 1" has written x+1. Deliberately only these - collapsing every space
#: would fold "5 m/s" into "5m/s" and, worse, "2 x" into "2x" in a subject
#: where those differ.
OPERATORS = re.compile(r"\s*([+\-*/=<>()])\s*")

WHITESPACE = re.compile(r"\s+")


def normalise(entry: str) -> str:
    """Fold an entry to the form both sides are compared in.

    Deliberately conservative. It removes what a teacher would never have
    marked down for - spacing, case, a trailing full stop, a keyboard's minus
    sign against a hyphen - and nothing else. It does not reorder terms, cancel
    fractions or evaluate anything, because each of those is a rule that is
    right in one subject and wrong in another.
    """

    text = unicodedata.normalize("NFKC", entry or "")
    for character, replacement in SUBSTITUTIONS.items():
        text = text.replace(character, replacement)
    text = WHITESPACE.sub(" ", text).strip().casefold()
    text = OPERATORS.sub(r"\1", text)
    while text and text[-1] in TRAILING:
        text = text[:-1].rstrip()
    return text


def matches(entry: str, accepted: list[str]) -> bool:
    """Whether the child's entry is one of the forms this step accepts.

    A step with no stored forms matches nothing. That is correct rather than
    permissive: an empty list means the pipeline could not enumerate the
    answers, and a step that accepts anything teaches a child that anything is
    right.
    """

    if not accepted:
        return False
    folded = normalise(entry)
    return bool(folded) and any(folded == normalise(form) for form in accepted)


def first_match(entry: str, accepted: list[str]) -> str | None:
    """Which stored form the entry matched, for the record of the attempt."""

    folded = normalise(entry)
    if not folded:
        return None
    return next((form for form in accepted if normalise(form) == folded), None)
