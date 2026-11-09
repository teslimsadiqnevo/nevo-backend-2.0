"""Turn a concept key into something a child can read.

A checkpoint's conceptName is written by the model, and it is supposed to be
the name of the idea. Often it is: "Energy transfer in food chains", "Problem
definition". Sometimes it is an identifier instead - conductorVsInsulator,
average_speed_calculation_practice, periodGroupDefinition, stack_pitfall -
and those went straight to a child's result screen. Finishing Heat Transfer,
Chidi read "You explored conductorVsInsulator, convectionMechanism,
radiationAbsorptionReflection, radiationProperties and radiationVsConvection
today", with five ticked rows of the same keys.

Applied when the lesson is read rather than only when it is written, because
the lessons already stored have these in them and a child should stop seeing
them today, not after a backfill.

The test is whitespace. A name a person wrote has spaces in it, or is a single
ordinary word; an identifier has underscores, hyphens or a capital in the
middle and no spaces at all. Anything with a space is left exactly as it is,
so "Kahn's Algorithm Execution" and "divide-and-conquer recurrence from code"
are not touched.
"""

from __future__ import annotations

import re

#: A run of capitals is an acronym and stays whole: HTMLParser is an HTML
#: parser, not a h t m l parser, and pHScale is a pH scale.
_BOUNDARY = re.compile(
    r"""
    (?<=[a-z0-9])(?=[A-Z])      # conductorVs  -> conductor | Vs
    |(?<=[A-Z])(?=[A-Z][a-z])   # HTMLParser   -> HTML | Parser
    |(?<=[a-zA-Z])(?=[0-9])     # group2       -> group | 2
    |(?<=[0-9])(?=[a-zA-Z])     # 2groups      -> 2 | groups
    """,
    re.VERBOSE,
)

#: Words that read wrong with a capital letter in the middle of a sentence,
#: and short forms a child meets in the lesson itself.
_KEEP_LOWER = frozenset({"vs", "and", "or", "of", "in", "to", "the", "a", "an", "per"})


def _is_identifier(value: str) -> bool:
    """Whether this looks like a key rather than a name somebody wrote."""
    if " " in value or "\t" in value:
        return False
    if "_" in value or "-" in value:
        return True
    # A capital after a lowercase letter, which no ordinary single word has.
    return bool(re.search(r"[a-z][A-Z]", value))


def readable_concept_name(value: object) -> str:
    """A concept name fit to show a child.

    Returns the value unchanged when it already reads as a name, including
    when it is empty - deciding what to do about a missing name belongs to
    the caller, which can see whether anything else names the idea.
    """
    if not isinstance(value, str):
        return ""
    name = " ".join(value.split())
    if not name or not _is_identifier(name):
        return name

    spaced = _BOUNDARY.sub(" ", name.replace("_", " ").replace("-", " "))
    words = spaced.split()
    if not words:
        return name

    # A single lowercase letter opening the name belongs to the word after
    # it: pH, mRNA, xRay. Split off on its own it reads as a stray letter.
    if len(words) > 1 and len(words[0]) == 1 and words[0].islower() and words[1][:1].isupper():
        words = [words[0] + words[1], *words[2:]]

    out: list[str] = []
    for index, word in enumerate(words):
        lowered = word.casefold()
        if word.isupper() and len(word) > 1:
            out.append(word)  # an acronym keeps its case
        elif index and lowered in _KEEP_LOWER:
            out.append(lowered)
        elif index:
            out.append(lowered)
        elif word.islower():
            out.append(word[0].upper() + word[1:])
        else:
            # Already mixed case, like pH: somebody meant that, leave it.
            out.append(word)
    return " ".join(out)
