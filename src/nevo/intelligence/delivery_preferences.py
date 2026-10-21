"""Explicit segment choices override engine defaults, never another segment."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SegmentChoiceWrite(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    modality: Literal["text", "audio", "visual", "interactive"] | None = None
    depth: Literal["original", "simplified", "expanded"] | None = None
    slower: bool | None = None


class SegmentChoice(SegmentChoiceWrite):
    updated_at: datetime | None = Field(default=None, alias="updatedAt")


def segment_choice(sitting, segment):
    return (
        ((sitting.delivery_state or {}).get("segmentChoices") or {}).get(str(segment.id), {})
        if sitting
        else {}
    )


def save_choice(sitting, segment, payload):
    delivery = dict(sitting.delivery_state or {})
    choices = dict(delivery.get("segmentChoices") or {})
    current = dict(choices.get(str(segment.id)) or {})
    current.update(payload.model_dump(exclude_unset=True, exclude={"updated_at"}, mode="json"))
    current["updatedAt"] = datetime.now(UTC).isoformat()
    choices[str(segment.id)] = current
    sitting.delivery_state = {**delivery, "segmentChoices": choices}
    return current
