"""Subjects: what a class is taught and what a teacher teaches.

Nevo had neither. A student was attached to a class and a teacher to a class,
and nothing said what subject any of it was about - which is why nothing could
report a child's progress by subject and why the student subject cards were
rendering a hard-coded curve.

Two lists, and the distinction matters. Nevo owns a canonical list so that
Mathematics reads identically in every school. A school can add one the list
does not hold, because our list covers Nigerian secondary well and will not
cover primary, Montessori or Cambridge - and a school that cannot enter its own
subject cannot use the product.
"""

from enum import StrEnum


class SubjectOrigin(StrEnum):
    """Where a subject on a school's list came from."""

    #: One of Nevo's own, chosen from the canonical list.
    CANONICAL = "canonical"
    #: The school typed its own. Behaves identically everywhere else.
    SCHOOL = "school"


class SubjectReviewState(StrEnum):
    """Where a school-added subject has got to in internal review.

    Every addition lands here with the school that made it and the words they
    typed, because that is how the canonical list grows out of real schools
    rather than out of a meeting. Expect near-duplicates - Maths against
    Mathematics - and expect to merge them.
    """

    #: Waiting to be looked at. The school is already using it.
    PENDING = "pending"
    #: Looked at and kept as the school's own. Not every subject belongs in
    #: the canonical list; a school's house name for something is legitimate.
    KEPT = "kept"
    #: Pointed at a canonical subject. The school's records are untouched -
    #: they reference the school's row, and that row now resolves to the
    #: canonical name.
    MERGED = "merged"


class SpellingAnswer(StrEnum):
    """What a school said about two spellings of one subject.

    Binary by design. "Maths and Mathematics, same subject or different?" has
    no third answer worth building a screen for, and the fuller spelling
    surviving a "same" is stated on screen rather than offered as an edit.
    """

    #: Nobody has been asked yet. The two are already folded into one.
    UNANSWERED = "unanswered"
    #: One subject. The fold stands and the fuller spelling survives.
    SAME = "same"
    #: Two subjects. Split back out, both labels kept exactly as written.
    DIFFERENT = "different"


#: A starting canonical list, from the Nigerian secondary curriculum: NERDC
#: junior and the WAEC senior syllabuses.
#:
#: Deliberately not presented as complete. The ticket says to seed from the
#: subject syllabuses in the curriculum research, and this is a defensible
#: starting set rather than that research - it is seeded through a migration so
#: it can be extended or replaced without touching code, and a school can add
#: what is missing in the meantime. Primary, Montessori and Cambridge-specific
#: subjects are knowingly absent.
CANONICAL_SUBJECTS: tuple[tuple[str, str], ...] = (
    ("mathematics", "Mathematics"),
    ("further-mathematics", "Further Mathematics"),
    ("english-language", "English Language"),
    ("literature-in-english", "Literature in English"),
    ("basic-science", "Basic Science"),
    ("basic-technology", "Basic Technology"),
    ("physics", "Physics"),
    ("chemistry", "Chemistry"),
    ("biology", "Biology"),
    ("agricultural-science", "Agricultural Science"),
    ("computer-studies", "Computer Studies"),
    ("economics", "Economics"),
    ("government", "Government"),
    ("commerce", "Commerce"),
    ("financial-accounting", "Financial Accounting"),
    ("geography", "Geography"),
    ("history", "History"),
    ("civic-education", "Civic Education"),
    ("social-studies", "Social Studies"),
    ("christian-religious-studies", "Christian Religious Studies"),
    ("islamic-studies", "Islamic Studies"),
    ("business-studies", "Business Studies"),
    ("home-economics", "Home Economics"),
    ("physical-and-health-education", "Physical and Health Education"),
    ("cultural-and-creative-arts", "Cultural and Creative Arts"),
    ("music", "Music"),
    ("french", "French"),
    ("yoruba", "Yoruba"),
    ("igbo", "Igbo"),
    ("hausa", "Hausa"),
    ("technical-drawing", "Technical Drawing"),
    ("food-and-nutrition", "Food and Nutrition"),
)
