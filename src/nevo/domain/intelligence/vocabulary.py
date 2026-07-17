from enum import StrEnum


class AdaptationMode(StrEnum):
    LESSON_LOAD = "lesson_load"
    IN_LESSON = "in_lesson"


class ContentModality(StrEnum):
    VISUAL = "visual"
    AUDIO = "audio"
    TEXT = "text"
    INTERACTIVE = "interactive"


class ContentSegmentType(StrEnum):
    DIAGRAM = "diagram"
    WORKED_EXAMPLE = "worked_example"
    EXPLANATION = "explanation"
    DEFINITION = "definition"
    SUMMARY = "summary"
    PRACTICE = "practice"
    INTERACTION = "interaction"
    CHECKPOINT = "checkpoint"


class DensityLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ScaffoldingLevel(StrEnum):
    LIGHT = "light"
    STANDARD = "standard"
    STRONG = "strong"


class BreakType(StrEnum):
    MICRO = "micro"
    MOVEMENT = "movement"
    CONSOLIDATION = "consolidation"
    FULL = "full"
