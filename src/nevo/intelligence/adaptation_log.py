from datetime import datetime
from typing import Protocol
from uuid import UUID

from nevo.domain.signal_events.vocabulary import SignalEventType
from nevo.intelligence.entities import AdaptationEventLogRecord

ADAPTATION_EVENT_TYPES = {
    SignalEventType.SIMPLIFY_TRIGGER,
    SignalEventType.EXPAND_TRIGGER,
    SignalEventType.SLOWER_TRIGGER,
    SignalEventType.BREAK_SUGGESTED,
    SignalEventType.MODALITY_SUGGESTION_SHOWN,
    SignalEventType.MODALITY_SUGGESTION_ACCEPTED,
    SignalEventType.MODALITY_SWITCH_OUTCOME,
    SignalEventType.MODALITY_MANUAL_SWITCH,
}


class AdaptationEventLogRepository(Protocol):
    async def events(
        self,
        *,
        school_id: UUID,
        class_id: UUID | None,
        student_id: UUID | None,
        lesson_id: UUID | None,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[AdaptationEventLogRecord, ...]: ...

    async def count(
        self,
        *,
        school_id: UUID,
        class_id: UUID | None,
        student_id: UUID | None,
        lesson_id: UUID | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> int: ...


class AdaptationEventLogService:
    def __init__(self, repository: AdaptationEventLogRepository) -> None:
        self._repository = repository

    async def events(
        self,
        *,
        school_id: UUID,
        class_id: UUID | None = None,
        student_id: UUID | None = None,
        lesson_id: UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[tuple[AdaptationEventLogRecord, ...], int]:
        bounded_limit = min(max(limit, 1), 100)
        bounded_offset = max(offset, 0)
        records = await self._repository.events(
            school_id=school_id,
            class_id=class_id,
            student_id=student_id,
            lesson_id=lesson_id,
            date_from=date_from,
            date_to=date_to,
            limit=bounded_limit,
            offset=bounded_offset,
        )
        total = await self._repository.count(
            school_id=school_id,
            class_id=class_id,
            student_id=student_id,
            lesson_id=lesson_id,
            date_from=date_from,
            date_to=date_to,
        )
        return records, total


def trigger_plain_language(
    event_type: SignalEventType,
    event_data: dict[str, object],
) -> str:
    if event_type is SignalEventType.MODALITY_SUGGESTION_SHOWN:
        reason = str(event_data.get("triggerReason") or "")
        return _reason_label(reason) if reason else "Learning pattern shift"
    if event_type is SignalEventType.MODALITY_SUGGESTION_ACCEPTED:
        return "Student accepted a suggested format change"
    if event_type is SignalEventType.MODALITY_SWITCH_OUTCOME:
        return "Format switch completed"
    if event_type is SignalEventType.MODALITY_MANUAL_SWITCH:
        return "Student selected a different format"
    if event_type is SignalEventType.SIMPLIFY_TRIGGER:
        return "Comprehension support requested"
    if event_type is SignalEventType.EXPAND_TRIGGER:
        return "High confidence signal"
    if event_type is SignalEventType.SLOWER_TRIGGER:
        return "Pacing support requested"
    if event_type is SignalEventType.BREAK_SUGGESTED:
        return "Attention or effort pattern shift"
    return "Learning pattern shift"


def adaptation_plain_language(
    event_type: SignalEventType,
    event_data: dict[str, object],
) -> str:
    if event_type in {
        SignalEventType.MODALITY_SUGGESTION_ACCEPTED,
        SignalEventType.MODALITY_MANUAL_SWITCH,
    }:
        return _format_shift(
            event_data.get("fromModality"),
            event_data.get("toModality"),
        )
    if event_type is SignalEventType.MODALITY_SUGGESTION_SHOWN:
        return _format_shift(
            event_data.get("fromModality") or event_data.get("currentModality"),
            event_data.get("suggestedModality"),
        )
    if event_type is SignalEventType.MODALITY_SWITCH_OUTCOME:
        return _format_shift(
            event_data.get("fromModality"),
            event_data.get("modality") or event_data.get("toModality"),
        )
    if event_type is SignalEventType.SIMPLIFY_TRIGGER:
        return "Original -> Simplified"
    if event_type is SignalEventType.EXPAND_TRIGGER:
        return "Core -> Expanded"
    if event_type is SignalEventType.SLOWER_TRIGGER:
        return "Standard pace -> Slower pace"
    if event_type is SignalEventType.BREAK_SUGGESTED:
        return "Lesson flow -> Break suggested"
    return "Content delivery adjusted"


def _reason_label(reason: str) -> str:
    labels = {
        "combined": "Comprehension declining + engagement drop",
        "low_engagement": "Engagement drop",
        "comprehension_decline": "Comprehension declining",
        "attention_pattern_shift": "Attention pattern shift",
        "high_visual_confidence": "High confidence in visual channel",
        "high_audio_confidence": "High confidence in audio channel",
        "high_interactive_confidence": "High confidence in interactive channel",
        "high_text_confidence": "High confidence in text channel",
    }
    return labels.get(reason, reason.replace("_", " ").capitalize())


def _format_shift(from_value: object, to_value: object) -> str:
    to_label = _modality_label(to_value)
    if not to_label:
        return "Content delivery adjusted"
    from_label = _modality_label(from_value)
    if from_label:
        return f"{from_label} -> {to_label}"
    return f"Switched to {to_label}"


def _modality_label(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    labels = {
        "text": "Text",
        "visual": "Visual",
        "audio": "Audio",
        "interactive": "Interactive",
    }
    return labels.get(text, text.replace("_", " ").title())
