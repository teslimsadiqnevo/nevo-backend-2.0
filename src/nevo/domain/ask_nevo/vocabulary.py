from enum import StrEnum


class AskNevoRole(StrEnum):
    """Who is asking, which decides both the prompt and the tools offered.

    Not the same list as UserRole: an admin asks the same kind of question a
    teacher does and gets the same voice, but reaches further into the school.
    """

    STUDENT = "student"
    TEACHER = "teacher"
    PARENT = "parent"
    ADMIN = "admin"


class AskNevoQuestionCategory(StrEnum):
    LESSON_HELP = "lesson_help"
    PROFILE_PATTERN = "profile_pattern"
    CLASS_PLANNING = "class_planning"
    FAMILY_MESSAGE = "family_message"
    FLAG_REVIEW = "flag_review"
    GENERAL = "general"


class AskNevoMessageAuthor(StrEnum):
    """Who said a thing in a thread.

    ``asker`` rather than ``user`` because the asker may be a learner, a
    teacher, a parent or an administrator, and the word has to fit all four.
    """

    ASKER = "asker"
    NEVO = "nevo"
