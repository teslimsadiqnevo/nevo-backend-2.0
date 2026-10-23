"""Depth and pacing belong to a sitting; format belongs to one segment."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LessonChoice(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    depth: Literal["original", "simplified", "expanded"] | None = None
    slower: bool | None = None
    updated_at: datetime | None = Field(default=None, alias="updatedAt")


class SegmentChoiceWrite(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    modality: Literal["text", "audio", "visual", "interactive"] | None = None
    depth: Literal["original", "simplified", "expanded"] | None = Field(
        default=None, description="Applies throughout this sitting, not only the addressed segment."
    )
    slower: bool | None = Field(
        default=None,
        description="Sitting-wide pacing choice; false explicitly switches Slower off.",
    )


class SegmentFormatChoice(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    modality: Literal["text", "audio", "visual", "interactive"] | None = None
    updated_at: datetime | None = Field(default=None, alias="updatedAt")


class SegmentChoice(SegmentChoiceWrite):
    updated_at: datetime | None = Field(default=None, alias="updatedAt")


def _active(sitting):
    return (
        sitting is not None
        and not getattr(sitting, "ended_at", None)
        and (getattr(sitting, "completion_status", "in_progress") == "in_progress")
    )


def lesson_choices(sitting):
    if not _active(sitting):
        return {}
    delivery = sitting.delivery_state or {}
    if "lessonPreferences" in delivery:
        return dict(delivery["lessonPreferences"] or {})
    # Upgrade old active sittings on read, using the latest explicit choice of each field.
    result = {}
    previous = sorted(
        (delivery.get("segmentChoices") or {}).values(),
        key=lambda item: str(item.get("updatedAt") or ""),
    )
    for choice in previous:
        for field in ("depth", "slower"):
            if field in choice:
                result[field] = choice[field]
                result["updatedAt"] = choice.get("updatedAt")
    return result


def delivery_for_read(sitting):
    delivery = dict(sitting.delivery_state or {})
    delivery["lessonPreferences"] = lesson_choices(sitting)
    delivery["segmentChoices"] = (
        {
            key: {
                field: value
                for field, value in choice.items()
                if field in {"modality", "updatedAt"}
            }
            for key, choice in (delivery.get("segmentChoices") or {}).items()
        }
        if _active(sitting)
        else {}
    )
    return delivery


def segment_choice(sitting, segment):
    if not _active(sitting):
        return {}
    stored = ((sitting.delivery_state or {}).get("segmentChoices") or {}).get(str(segment.id), {})
    local = {key: value for key, value in stored.items() if key in {"modality", "updatedAt"}}
    choice = {**local, **lesson_choices(sitting)}
    if "modality" in choice:
        from nevo.api.lesson_contracts import student_modalities

        if choice["modality"] not in student_modalities(segment):
            choice.pop("modality")
    if choice.get("depth") in {"simplified", "expanded"} and hasattr(segment, "depth_variants"):
        from nevo.api.lesson_contracts import depth_approved

        variant = (segment.depth_variants or {}).get(choice["depth"])
        if not variant or not depth_approved(variant):
            choice["depth"] = "original"
    return choice


def save_choice(sitting, segment, payload):
    delivery = dict(sitting.delivery_state or {})
    choices = dict(delivery.get("segmentChoices") or {})
    lesson = lesson_choices(sitting)
    updates = payload.model_dump(exclude_unset=True, exclude={"updated_at"}, mode="json")
    now = datetime.now(UTC).isoformat()
    for field in ("depth", "slower"):
        if field in updates:
            lesson[field] = updates[field]
            lesson["updatedAt"] = now
    choices = {
        key: {field: value for field, value in choice.items() if field in {"modality", "updatedAt"}}
        for key, choice in choices.items()
    }
    if "modality" in updates:
        choices[str(segment.id)] = {"modality": updates["modality"], "updatedAt": now}
    sitting.delivery_state = {**delivery, "segmentChoices": choices, "lessonPreferences": lesson}
    return segment_choice(sitting, segment)
