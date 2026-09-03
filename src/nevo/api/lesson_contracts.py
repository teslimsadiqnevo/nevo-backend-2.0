from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ScalarAnswer = str | int | float | bool


class CheckpointOption(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    value: ScalarAnswer
    label: str


class ComprehensionCheckpoint(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    concept_id: UUID | None = Field(default=None, alias="conceptId")
    concept_name: str | None = Field(default=None, alias="conceptName")
    prompt: str
    answer_type: Literal["single_choice", "multiple_choice", "text", "numeric", "boolean"] = (
        Field(default="text", alias="answerType")
    )
    options: list[CheckpointOption] = Field(default_factory=list)
    answer_key: ScalarAnswer | list[ScalarAnswer] | None = Field(default=None, alias="answerKey")
    explanation: str | None = None
    position: str = "after_segment"


class TextVariant(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    body: str = ""
    key_points: list[str] = Field(default_factory=list, alias="keyPoints")


class VisualVariant(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["ai_generated_image"] = "ai_generated_image"
    image_url: str = Field(alias="imageUrl")
    storage_path: str = Field(alias="storagePath")
    prompt: str
    provider: str
    reviewed_by: str | None = Field(default=None, alias="reviewedBy")
    review_attempts: int = Field(default=0, alias="reviewAttempts")
    generated_at: str = Field(alias="generatedAt")
    caption: str
    quality_validated: bool = Field(default=True, alias="qualityValidated")
    url_expires_in_seconds: int | None = Field(default=None, alias="urlExpiresInSeconds")


class AudioVariant(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    script: str
    audio_url: str = Field(alias="audioUrl")
    storage_path: str | None = Field(default=None, alias="storagePath")
    duration_ms: int = Field(default=0, alias="durationMs")
    provider: str
    voice: str | None = None
    format: Literal["mp3"] = "mp3"
    requires_authentication: bool = Field(default=False, alias="requiresAuthentication")
    url_expires_in_seconds: int | None = Field(default=None, alias="urlExpiresInSeconds")
    step_id: str | None = Field(default=None, alias="stepId")


class InteractiveVariant(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: str = "practice_problem"
    prompt: str = ""
    expected_interaction: str = Field(
        default="teacher_review", alias="expectedInteraction"
    )
    options: list[CheckpointOption] = Field(default_factory=list)
    answer_key: ScalarAnswer | list[ScalarAnswer] | None = Field(default=None, alias="answerKey")
    instructions: str | None = None


class CalculationStep(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    step_id: str = Field(alias="stepId")
    step_number: int = Field(alias="stepNumber")
    prompt: str
    expected_input: Literal["selection", "numeric", "text", "drag"] = Field(
        alias="expectedInput"
    )
    hint: str
    confirmation_text: str = Field(alias="confirmationText")
    visual_update: str = Field(alias="visualUpdate")
    equation_state: str = Field(alias="equationState")
    narration_audio: AudioVariant | None = Field(default=None, alias="narrationAudio")


class ScaffoldImage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    image_url: str | None = Field(default=None, alias="imageUrl")
    storage_path: str | None = Field(default=None, alias="storagePath")
    prompt: str | None = None
    caption: str | None = None


class CalculationVariant(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["co_construction"] = "co_construction"
    full_equation: str = Field(alias="fullEquation")
    steps: list[CalculationStep]
    scaffold_image: ScaffoldImage | None = Field(default=None, alias="scaffoldImage")
    completion_statement: str = Field(alias="completionStatement")


def checkpoint_payloads(
    values: list[dict[str, object]], *, segment_key: str, concept_id: UUID | None = None
) -> list[dict[str, object]]:
    """Normalize older parser output into the documented checkpoint contract."""
    result: list[dict[str, object]] = []
    for index, value in enumerate(values, start=1):
        item = dict(value)
        item.setdefault("id", f"{segment_key}-check-{index}")
        item.setdefault("prompt", "Check your understanding of this part.")
        if item.get("answerType") not in {
            "single_choice",
            "multiple_choice",
            "text",
            "numeric",
            "boolean",
        }:
            item["answerType"] = _answer_type(item)
        item["options"] = _options(item.get("options"))
        answer_key = item.get("answerKey")
        if isinstance(answer_key, list):
            item["answerKey"] = [
                answer
                for answer in answer_key
                if isinstance(answer, (str, int, float, bool))
            ]
        elif not isinstance(answer_key, (str, int, float, bool, type(None))):
            item["answerKey"] = None
        item.setdefault("answerKey", None)
        if item.get("explanation") is not None:
            item["explanation"] = str(item["explanation"])
        item.setdefault("position", "after_segment")
        if concept_id is not None:
            item.setdefault("conceptId", str(concept_id))
        result.append(ComprehensionCheckpoint.model_validate(item).model_dump(by_alias=True))
    return result


def _options(value: object) -> list[dict[str, ScalarAnswer]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, ScalarAnswer]] = []
    for option in value:
        if isinstance(option, (str, int, float, bool)):
            result.append({"value": option, "label": str(option)})
        elif isinstance(option, dict) and isinstance(
            option.get("value"), (str, int, float, bool)
        ):
            raw = option["value"]
            result.append({"value": raw, "label": str(option.get("label") or raw)})
    return result


def _answer_type(item: dict[str, object]) -> str:
    if item.get("options"):
        return "single_choice"
    answer = item.get("answerKey")
    if isinstance(answer, bool):
        return "boolean"
    if isinstance(answer, (int, float)):
        return "numeric"
    return "text"
