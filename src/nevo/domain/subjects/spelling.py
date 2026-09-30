"""Two spellings of one subject, and how we tell.

A teacher file carries Maths on one row and Mathematics on another. Treated as
two subjects, a child's mastery splits across two knowledge graphs and their
progress halves for no reason - so they are mapped to one by default, and the
question is put to the school afterwards rather than in the middle of
onboarding, because a subject spelling does not change the invoice.

The question is only ever asked about spellings this file recognises as a
possible pair. A subject Nevo has never heard of is the school's own, accepted
as given, with no prompt: that is stated in SCRUM-204 and enforced by
``possible_pair`` returning False for anything it cannot argue for.
"""

from __future__ import annotations

#: Short forms schools actually write, against the canonical slug they mean.
#: Only unambiguous ones. "Further Maths" is not Mathematics and is left to
#: the prefix rule, which will not claim it either.
ABBREVIATIONS: dict[str, str] = {
    "maths": "mathematics",
    "math": "mathematics",
    "further maths": "further mathematics",
    "english": "english language",
    "eng": "english language",
    "lit in english": "literature in english",
    "bio": "biology",
    "chem": "chemistry",
    "phy": "physics",
    "phys": "physics",
    "agric": "agricultural science",
    "agric science": "agricultural science",
    "computer": "computer studies",
    "computer science": "computer studies",
    "ict": "computer studies",
    "civic": "civic education",
    "crs": "christian religious studies",
    "irs": "islamic studies",
    "islamic religious studies": "islamic studies",
    "phe": "physical and health education",
    "pe": "physical and health education",
    "business studs": "business studies",
    "home econs": "home economics",
    "social studs": "social studies",
    "basic sci": "basic science",
    "basic tech": "basic technology",
    "govt": "government",
    "accounting": "financial accounting",
}

#: A prefix shorter than this claims too much. "Bio" against "Biology" is
#: handled by the table above precisely so this can stay conservative:
#: "Art" must not swallow "Arithmetic".
SHORTEST_PREFIX = 5


def fold(name: str) -> str:
    """Case and inner spacing folded, the same way subject resolution folds."""

    return " ".join(name.split()).casefold()


def expand(name: str) -> str:
    """The fuller spelling of a short form, where we know one."""

    folded = fold(name)
    return ABBREVIATIONS.get(folded, folded)


def possible_pair(left: str, right: str) -> bool:
    """Whether these two spellings are worth asking one question about.

    True where a known short form expands onto the other, or where one is a
    long-enough prefix of the other - Mathematic against Mathematics, a
    dropped letter. False everywhere else, including for two subjects that
    merely start alike.
    """

    first, second = fold(left), fold(right)
    if first == second:
        return False
    if expand(first) == expand(second):
        return True
    shorter, longer = sorted((first, second), key=len)
    return len(shorter) >= SHORTEST_PREFIX and longer.startswith(shorter)


def fuller(left: str, right: str) -> str:
    """Which spelling survives a merge: the fuller one, per SCRUM-204."""

    return max((left, right), key=lambda value: (len(fold(value)), value))
