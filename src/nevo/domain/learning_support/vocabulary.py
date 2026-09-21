from enum import StrEnum


class AccommodationChangeAction(StrEnum):
    """Whether Nevo started doing something for a child, or stopped.

    Two words rather than a boolean, because "added: false" is read wrongly
    by everyone at least once and this log is read by people outside
    engineering.
    """

    ADDED = "added"
    REMOVED = "removed"


class AnnotationOrigin(StrEnum):
    """Who wrote a passage of a learning support document.

    Rendered beside every block, so a parent reading it is never unsure which
    words are their school's and which are Nevo's - and neither is a
    regulator reading it afterwards.
    """

    NEVO = "nevo"
    SCHOOL_STAFF = "school_staff"
