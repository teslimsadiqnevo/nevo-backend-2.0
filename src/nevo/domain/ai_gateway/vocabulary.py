from enum import IntEnum, StrEnum


class AiService(StrEnum):
    ADAPTATION = "adaptation"
    LESSON_GENERATION = "lesson_generation"
    NARRATIVE = "narrative"


class AiPriority(IntEnum):
    ADAPTATION = 0
    LESSON_GENERATION = 10
    NARRATIVE = 20


SERVICE_PRIORITIES = {
    AiService.ADAPTATION: AiPriority.ADAPTATION,
    AiService.LESSON_GENERATION: AiPriority.LESSON_GENERATION,
    AiService.NARRATIVE: AiPriority.NARRATIVE,
}


class AiCallStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FALLBACK = "fallback"
    FAILED = "failed"


class AiProviderName(StrEnum):
    GEMINI = "gemini"
    RULE_BASED = "rule_based"
