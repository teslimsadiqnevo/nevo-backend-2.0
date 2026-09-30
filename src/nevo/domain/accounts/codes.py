"""The school code a teacher reads out to a class. SCRUM-201.

Four characters, no prefix, from a deliberately reduced alphabet. It is spoken
aloud across a classroom and typed by a child, so every character that gets
misheard or misread is removed rather than explained.

Zero and capital O are the same shape in most fonts, and so are one and
capital I. A code containing either costs a support call, and support calls
about signing in happen on the first morning of term when nobody has time for
them. L stays, per the ruling.
"""

from __future__ import annotations

import secrets

#: Every letter and digit except 0, O, 1 and I.
#:
#: 32 symbols, four characters: about 1.05 million codes. A school reads its
#: own aloud, so the alphabet being small matters more than the space being
#: large.
SCHOOL_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"

SCHOOL_CODE_LENGTH = 4


def new_school_code() -> str:
    """One code. Uniqueness is the database's job, not this function's.

    ``secrets`` rather than ``random`` because a guessable school code is a
    guessable half of a child's sign-in.
    """

    return "".join(secrets.choice(SCHOOL_CODE_ALPHABET) for _ in range(SCHOOL_CODE_LENGTH))


def is_school_code(value: str) -> bool:
    """Whether a string could be one of ours.

    Used to tell a mistyped code from a code for a school we do not have, so
    the screen can say which.
    """

    folded = value.strip().upper()
    return len(folded) == SCHOOL_CODE_LENGTH and all(
        character in SCHOOL_CODE_ALPHABET for character in folded
    )


def normalise_school_code(value: str) -> str:
    """What a child typed, as the database stores it.

    Stripped and upper cased, and nothing else. There is deliberately no
    mapping of 0 to O or 1 to I: both members of each confusable pair are out
    of the alphabet, so a code never contains either and there is no ambiguity
    to resolve. A typed 0 is not a misread O - it is a character no code has,
    which ``is_school_code`` reports so the screen can say "check the code"
    rather than "no such school".
    """

    return value.strip().upper()
