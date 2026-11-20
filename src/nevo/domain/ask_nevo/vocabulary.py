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


class AskNevoRefusalReason(StrEnum):
    """Why a request to ask Nevo was refused, as a closed set.

    The 403 used to carry a code and a sentence, and the code was the same
    one for every role refusal. A screen that wants to say something useful -
    offer to switch role, or explain that a teacher cannot read another
    child's history - had nothing to switch on but the prose, and prose is
    not an interface: it gets reworded and the screen breaks silently.

    Closed rather than free text for the same reason the refusal set on the
    paper-work route is closed. A new reason is a deliberate addition here,
    visible in the schema, rather than a new sentence somebody wrote in a
    route. T8, 20 November.
    """

    #: This account may ask Nevo, but not in the role it asked in - a teacher
    #: asking as an admin, for instance. The screen can offer the roles that
    #: are available instead of only refusing.
    ROLE_NOT_AVAILABLE_TO_ACCOUNT = "role_not_available_to_account"
    #: This kind of account cannot ask Nevo in any role at all, so there is
    #: nothing to offer and the screen should not show the entry point.
    ACCOUNT_CANNOT_ASK = "account_cannot_ask"
    #: A learner asked about a learner who is not them. Distinct from the two
    #: above because nothing about the role is wrong: the context is.
    ANOTHER_LEARNERS_CONTEXT = "another_learners_context"
