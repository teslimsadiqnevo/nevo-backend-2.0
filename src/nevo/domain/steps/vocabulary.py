"""How much help a step needs, and how a child's working is laid out.

The support ladder is what the pipeline drops down when it cannot do the thing
above. It is a ladder rather than a switch because coverage is measured, not
assumed: of 344 topics mapped across the NERDC primary, junior and revised
curricula and the WAEC senior syllabuses, 278 reach level 1, 43 reach level 2
and 22 fall to level 4. A pipeline that could only do level 1 would silently
produce nothing for a fifth of the curriculum.
"""

from enum import StrEnum


class SupportLevel(StrEnum):
    """What the child is asked to do, in descending order of independence.

    Recorded per segment so coverage can be measured against real lessons after
    a term, rather than argued about from the matrix.
    """

    #: The child builds each step and it is matched against the stored forms.
    BUILD = "build"
    #: Too many valid forms to enumerate, so the child picks the next move from
    #: generated candidates - including plausible wrong ones.
    CHOOSE = "choose"
    #: Steps revealed one at a time with nothing judged. Worked example.
    REVEAL = "reveal"
    #: No step-by-step at all: an ordinary segment with Simplify, Expand and
    #: Slower. The honest floor rather than a bad approximation of the others.
    ORDINARY = "ordinary"


class WorkingLayout(StrEnum):
    """How the working is arranged on screen.

    Emitted per segment so the player renders what the subject needs rather
    than forcing every subject through a column of equations.
    """

    #: One equation refined down the page. Arithmetic and algebra.
    EQUATION = "equation"
    #: A column of figures aligned on place value. Long multiplication.
    COLUMN = "column"
    #: Free-standing statements in order. Proofs, method marks, science.
    STEPS = "steps"
    #: A table the child fills in. Data handling, substitution.
    TABLE = "table"
