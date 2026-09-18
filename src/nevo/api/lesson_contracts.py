from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from nevo.domain.intelligence.vocabulary import ManipulativeKind

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
    answer_type: Literal["single_choice", "multiple_choice", "text", "numeric", "boolean"] = Field(
        default="text", alias="answerType"
    )
    options: list[CheckpointOption] = Field(default_factory=list)
    answer_key: ScalarAnswer | list[ScalarAnswer] | None = Field(default=None, alias="answerKey")
    explanation: str | None = None
    position: str = "after_segment"


class TextVariant(BaseModel):
    """The text modality of a segment.

    ``body`` is the same string as the segment's own ``body`` - always, and
    enforced at parse time. They were independently settable, which meant the
    teacher's review screen and the student player could have shown different
    words and the approval gate would have been guarding the wrong one. There
    is one text; this is a view onto it for clients that read the variant
    rather than the segment.
    """

    model_config = ConfigDict(populate_by_name=True)

    body: str = Field(
        default="",
        description=(
            "Identical to the segment's body. One text, sent in both places so "
            "a client can read whichever shape suits it."
        ),
    )
    key_points: list[str] = Field(
        default_factory=list,
        alias="keyPoints",
        max_length=6,
        description=(
            "Highlights that sit beside the body, not a shorter retelling of "
            "it. A point that restates the whole body is dropped at parse "
            "time rather than shown twice."
        ),
    )


class VisualVariant(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["ai_generated_image"] = "ai_generated_image"
    #: The image to render. WebP at the resolution it was drawn at, because
    #: these pictures carry small text and shrinking them costs a child the
    #: diagram.
    image_url: str = Field(alias="imageUrl")
    #: A much smaller copy of the same picture, for a card or a list, or to
    #: paint something before the full one arrives on a slow connection.
    #: Absent on images stored before this existed.
    preview_url: str | None = Field(default=None, alias="previewUrl")
    #: The display image's own dimensions, so a client can hold the space
    #: before the bytes land rather than reflowing the lesson around it.
    width: int = 0
    height: int = 0
    #: Bytes of the display image. Zero on anything stored before this
    #: existed, and on a cache hit where nothing was re-encoded.
    byte_size: int = Field(default=0, alias="byteSize")
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
    #: None when nothing measured it. Zero used to be sent for every
    #: narration, which reads as a silent clip rather than an unknown length.
    duration_ms: int | None = Field(default=None, alias="durationMs")
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
    expected_interaction: str = Field(default="teacher_review", alias="expectedInteraction")
    options: list[CheckpointOption] = Field(default_factory=list)
    answer_key: ScalarAnswer | list[ScalarAnswer] | None = Field(default=None, alias="answerKey")
    instructions: str | None = None


class CalculationStep(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    step_id: str = Field(alias="stepId")
    step_number: int = Field(alias="stepNumber")
    prompt: str
    expected_input: Literal["selection", "numeric", "text", "drag"] = Field(alias="expectedInput")
    hint: str
    #: What this one step is answered with, in the units the step asks for.
    #: The variant's own answer is the whole problem's total; a step inside a
    #: fraction scaffold might want a numerator, so mapping the total onto the
    #: last step would be wrong even when it looks right.
    answer: ScalarAnswer | None = None
    #: What a selection or drag step offers. Empty for numeric and text, where
    #: the child types. Same shape as a checkpoint's options, so one renderer
    #: serves both.
    options: list[CheckpointOption] = Field(default_factory=list)
    #: What the answer is counted in - "naira", "years", "%" - when saying so
    #: makes the step answerable. Empty when the prompt already carries it.
    unit: str | None = None
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


class Manipulative(BaseModel):
    """What a learner drags, and what it is made of.

    A step could already declare expectedInput "drag" and carried nothing to
    drag, so drag was refused on generated content - which is why the one
    place modalities layer rather than switch could not happen. The shape is
    deliberately small: a kind the client has a renderer for, how many pieces
    the whole is cut into, and how those pieces are laid out.
    """

    model_config = ConfigDict(populate_by_name=True)

    kind: ManipulativeKind
    #: How many equal pieces the whole is divided into - the denominator of a
    #: fraction bar, the columns of an array, the ticks on a number line.
    parts: int = Field(ge=1, le=100)
    #: How many rows those pieces are arranged in. One for a bar or a line;
    #: an array of twelve as 3x4 is three.
    rows: int = Field(default=1, ge=1, le=20)
    #: What each piece is called when a child reads it aloud, if naming them
    #: helps. Empty when the pieces need no label.
    labels: list[str] = Field(default_factory=list, max_length=100)


class CalculationVariant(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["co_construction"] = "co_construction"
    full_equation: str = Field(alias="fullEquation")
    #: What the whole problem comes to. Sent rather than left to be inferred
    #: from the last step: this is what a child is marked against, and a
    #: client guessing it would be guessing the mark.
    answer: str = ""
    steps: list[CalculationStep]
    scaffold_image: ScaffoldImage | None = Field(default=None, alias="scaffoldImage")
    #: Present when the steps are meant to be dragged rather than typed. Null
    #: when this calculation is worked through in numbers alone.
    manipulative: Manipulative | None = None
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
                answer for answer in answer_key if isinstance(answer, (str, int, float, bool))
            ]
        elif not isinstance(answer_key, (str, int, float, bool, type(None))):
            item["answerKey"] = None
        item.setdefault("answerKey", None)
        if item.get("explanation") is not None:
            item["explanation"] = str(item["explanation"])
        item.setdefault("position", "after_segment")
        if concept_id is not None:
            item.setdefault("conceptId", str(concept_id))
        # mode="json" because this payload is written straight into a JSONB
        # column. A plain dump leaves conceptId as a UUID object, and the
        # insert then fails on every segment that carries a checkpoint - which
        # is why a parse could run to completion and still store nothing.
        result.append(
            ComprehensionCheckpoint.model_validate(item).model_dump(
                by_alias=True,
                mode="json",
            )
        )
    return result


def _options(value: object) -> list[dict[str, ScalarAnswer]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, ScalarAnswer]] = []
    for option in value:
        if isinstance(option, (str, int, float, bool)):
            result.append({"value": option, "label": str(option)})
        elif isinstance(option, dict) and isinstance(option.get("value"), (str, int, float, bool)):
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
