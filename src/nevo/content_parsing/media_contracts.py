from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from nevo.api.casing import CAMEL_CONFIG
from nevo.api.lesson_contracts import AudioVariant, VisualVariant


class MediaCounts(BaseModel):
    model_config = CAMEL_CONFIG
    total: int = 0
    queued: int = 0
    processing: int = 0
    awaiting_review: int = 0
    approved: int = 0
    failed: int = 0
    stale: int = 0
    withdrawn: int = 0


class MediaPreparation(BaseModel):
    model_config = CAMEL_CONFIG
    phase: Literal[
        "not_requested", "preparing", "awaiting_review", "complete", "complete_with_errors"
    ]
    generation_complete: bool
    images: MediaCounts
    audio: MediaCounts


class StepNarration(BaseModel):
    model_config = CAMEL_CONFIG
    step_id: str
    audio: AudioVariant


class PreparedMedia(BaseModel):
    model_config = CAMEL_CONFIG
    image: VisualVariant | None = None
    audio: AudioVariant | None = None
    step_narrations: list[StepNarration] = Field(default_factory=list)


class LessonMediaItem(BaseModel):
    model_config = CAMEL_CONFIG
    id: UUID
    segment_id: UUID
    kind: Literal["image", "audio"]
    status: Literal[
        "queued", "processing", "awaiting_review", "approved", "failed", "stale", "withdrawn"
    ]
    asset: PreparedMedia | None
    source_changed: bool
    failure_code: str | None
    created_at: datetime
    completed_at: datetime | None
    approved_at: datetime | None
    approved_by: UUID | None
    approved_by_name: str | None
    withdrawn_at: datetime | None = None
    withdrawn_by: UUID | None = None
    withdrawn_by_name: str | None = None
    withdrawal_reason: str | None = None
    withdrawal_reason_by: UUID | None = None
    withdrawal_reason_at: datetime | None = None
    can_undo: bool = False
    undo_unavailable_reason: Literal[
        "media_withdrawal_already_restored",
        "media_withdrawal_undo_expired",
        "media_restore_source_changed",
        "media_restore_review_required",
    ] | None = None
    undo_available_until: datetime | None = None
    restored_at: datetime | None = None
    restored_by: UUID | None = None
    restored_by_name: str | None = None


class LessonMediaResponse(BaseModel):
    model_config = CAMEL_CONFIG
    lesson_id: UUID
    summary: MediaPreparation
    items: list[LessonMediaItem]
