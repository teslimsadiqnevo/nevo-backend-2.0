from enum import StrEnum


class AskNevoRole(StrEnum):
    STUDENT = "student"
    TEACHER = "teacher"


class AskNevoQuestionCategory(StrEnum):
    LESSON_HELP = "lesson_help"
    PROFILE_PATTERN = "profile_pattern"
    CLASS_PLANNING = "class_planning"
    FAMILY_MESSAGE = "family_message"
    FLAG_REVIEW = "flag_review"
    GENERAL = "general"
