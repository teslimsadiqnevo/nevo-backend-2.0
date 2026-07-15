import json
import uuid
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.ai_gateway.entities import AiGenerationRequest
from nevo.ai_gateway.service import AiGatewayService
from nevo.db.models.learner_profile import (
    LearnerProfile,
    LearnerProfileAttentionFlag,
    LearnerProfileHistory,
)
from nevo.db.models.signal_event import LessonSession, SignalEvent
from nevo.domain.ai_gateway.vocabulary import AiService
from nevo.domain.learner_profiles.vocabulary import (
    CANONICAL_PROFILE_DIMENSIONS,
    ChannelPreferenceStrength,
    ConfidenceLevel,
    ProfileAttentionFlagStatus,
    ProfileChangeSource,
)

CHANNEL_DIMENSIONS = frozenset(
    {
        "visual_spatial_preference",
        "auditory_preference",
        "reading_writing_preference",
        "interactive_kinesthetic_preference",
    }
)
NUMERIC_DIMENSIONS = frozenset(CANONICAL_PROFILE_DIMENSIONS).difference(
    CHANNEL_DIMENSIONS
)
PROFILE_UPDATE_PROMPT_NAME = "profile_update.default"


class ProfileUpdateStatus(StrEnum):
    UPDATED = "updated"
    FLAGGED = "flagged"
    NO_CHANGE = "no_change"


class ProfileUpdateResponseError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProfileDimensionState:
    value: int | ChannelPreferenceStrength | None
    confidence: ConfidenceLevel


@dataclass(frozen=True, slots=True)
class ProfileDimensionRecommendation:
    dimension: str
    value: int | ChannelPreferenceStrength | None
    confidence: ConfidenceLevel
    rationale: str | None = None


@dataclass(frozen=True, slots=True)
class SessionProfileUpdateContext:
    student_id: UUID
    lesson_session_id: UUID
    learner_profile_id: UUID | None
    current_profile: Mapping[str, ProfileDimensionState]
    session_summary: Mapping[str, object]
    event_count: int


@dataclass(frozen=True, slots=True)
class ProfileUpdateRecord:
    profile_id: UUID
    history_id: UUID
    version: int


@dataclass(frozen=True, slots=True)
class ProfileAttentionFlagDraft:
    dimension: str
    current_value: str | None
    recommended_value: str | None
    rationale: str


@dataclass(frozen=True, slots=True)
class ProfileUpdateOutcome:
    status: ProfileUpdateStatus
    profile_id: UUID | None
    dimensions: tuple[str, ...] = ()
    history_id: UUID | None = None
    flag_id: UUID | None = None
    reason: str | None = None


class PostLessonProfileUpdateRepository(Protocol):
    async def load_context(
        self,
        *,
        student_id: UUID,
        lesson_session_id: UUID,
    ) -> SessionProfileUpdateContext: ...

    async def apply_recommendations(
        self,
        *,
        context: SessionProfileUpdateContext,
        recommendations: Iterable[ProfileDimensionRecommendation],
        changed_by: UUID,
        change_reason: str,
        evaluated_at: datetime,
    ) -> ProfileUpdateRecord: ...

    async def create_attention_flag(
        self,
        *,
        context: SessionProfileUpdateContext,
        flag: ProfileAttentionFlagDraft,
    ) -> UUID: ...


class PostLessonProfileUpdateService:
    def __init__(
        self,
        *,
        repository: PostLessonProfileUpdateRepository,
        gateway: AiGatewayService,
    ) -> None:
        self._repository = repository
        self._gateway = gateway

    async def update_after_lesson(
        self,
        *,
        student_id: UUID,
        lesson_session_id: UUID,
        requested_by_user_id: UUID,
    ) -> ProfileUpdateOutcome:
        context = await self._repository.load_context(
            student_id=student_id,
            lesson_session_id=lesson_session_id,
        )
        result = await self._gateway.generate(
            AiGenerationRequest(
                requester_user_id=requested_by_user_id,
                student_id=student_id,
                service=AiService.NARRATIVE,
                prompt_name=PROFILE_UPDATE_PROMPT_NAME,
                variables={
                    "current_profile": json.dumps(
                        _profile_for_prompt(context.current_profile),
                        sort_keys=True,
                    ),
                    "session_summary": json.dumps(
                        context.session_summary,
                        sort_keys=True,
                        default=str,
                    ),
                },
                max_output_tokens=1_024,
            )
        )
        recommendations, rationale = parse_profile_update_response(result.text)
        if not recommendations:
            return ProfileUpdateOutcome(
                status=ProfileUpdateStatus.NO_CHANGE,
                profile_id=context.learner_profile_id,
                reason=rationale,
            )

        divergence = detect_sudden_change(
            current_profile=context.current_profile,
            recommendations=recommendations,
        )
        if divergence is not None:
            flag_id = await self._repository.create_attention_flag(
                context=context,
                flag=divergence,
            )
            return ProfileUpdateOutcome(
                status=ProfileUpdateStatus.FLAGGED,
                profile_id=context.learner_profile_id,
                flag_id=flag_id,
                dimensions=(divergence.dimension,),
                reason=divergence.rationale,
            )

        record = await self._repository.apply_recommendations(
            context=context,
            recommendations=recommendations,
            changed_by=requested_by_user_id,
            change_reason=rationale or "Post-lesson profile update",
            evaluated_at=datetime.now(UTC),
        )
        return ProfileUpdateOutcome(
            status=ProfileUpdateStatus.UPDATED,
            profile_id=record.profile_id,
            history_id=record.history_id,
            dimensions=tuple(item.dimension for item in recommendations),
        )


def parse_profile_update_response(
    response_text: str,
) -> tuple[tuple[ProfileDimensionRecommendation, ...], str | None]:
    try:
        payload = json.loads(_json_payload(response_text))
    except json.JSONDecodeError as error:
        raise ProfileUpdateResponseError("Profile update response is not JSON") from error
    if not isinstance(payload, dict):
        raise ProfileUpdateResponseError("Profile update response must be an object")

    updates_payload = payload.get("updates", ())
    if isinstance(updates_payload, dict):
        items = [
            {"dimension": dimension, **update}
            for dimension, update in updates_payload.items()
            if isinstance(update, dict)
        ]
    elif isinstance(updates_payload, list):
        items = updates_payload
    else:
        raise ProfileUpdateResponseError("Profile update response has invalid updates")

    recommendations: list[ProfileDimensionRecommendation] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        dimension = item.get("dimension")
        if dimension not in CANONICAL_PROFILE_DIMENSIONS:
            continue
        recommendations.append(
            ProfileDimensionRecommendation(
                dimension=dimension,
                value=_coerce_profile_value(dimension, item.get("value")),
                confidence=ConfidenceLevel(str(item.get("confidence", "low"))),
                rationale=_optional_string(item.get("rationale")),
            )
        )
    rationale = _optional_string(payload.get("rationale"))
    return tuple(recommendations), rationale


def detect_sudden_change(
    *,
    current_profile: Mapping[str, ProfileDimensionState],
    recommendations: Iterable[ProfileDimensionRecommendation],
) -> ProfileAttentionFlagDraft | None:
    for recommendation in recommendations:
        current = current_profile.get(recommendation.dimension)
        if current is None or current.confidence is not ConfidenceLevel.HIGH:
            continue
        if current.value is None or recommendation.value is None:
            continue
        if not _is_significant_change(
            recommendation.dimension,
            current.value,
            recommendation.value,
        ):
            continue
        return ProfileAttentionFlagDraft(
            dimension=recommendation.dimension,
            current_value=_serialize_profile_value(current.value),
            recommended_value=_serialize_profile_value(recommendation.value),
            rationale=(
                recommendation.rationale
                or "Session evidence diverged from a high-confidence profile value."
            ),
        )
    return None


class SqlAlchemyPostLessonProfileUpdateRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def load_context(
        self,
        *,
        student_id: UUID,
        lesson_session_id: UUID,
    ) -> SessionProfileUpdateContext:
        async with self._sessions() as session:
            lesson_session = await session.get(LessonSession, lesson_session_id)
            if lesson_session is None or lesson_session.student_id != student_id:
                raise LookupError("Lesson session was not found for student")
            profile = await session.scalar(
                select(LearnerProfile).where(
                    LearnerProfile.learner_id == student_id
                )
            )
            events = (
                await session.scalars(
                    select(SignalEvent)
                    .where(
                        SignalEvent.student_id == student_id,
                        SignalEvent.session_id == lesson_session_id,
                    )
                    .order_by(SignalEvent.timestamp)
                )
            ).all()
            current_profile = (
                _profile_from_model(profile)
                if profile is not None
                else _empty_profile_state()
            )
            return SessionProfileUpdateContext(
                student_id=student_id,
                lesson_session_id=lesson_session_id,
                learner_profile_id=profile.id if profile is not None else None,
                current_profile=current_profile,
                session_summary=_session_summary(lesson_session, events),
                event_count=len(events),
            )

    async def apply_recommendations(
        self,
        *,
        context: SessionProfileUpdateContext,
        recommendations: Iterable[ProfileDimensionRecommendation],
        changed_by: UUID,
        change_reason: str,
        evaluated_at: datetime,
    ) -> ProfileUpdateRecord:
        async with self._sessions.begin() as session:
            profile = await _load_or_create_profile(session, context.student_id)
            profile.version += 1
            profile.observed_event_count += context.event_count
            profile.last_evaluated_at = evaluated_at
            for recommendation in recommendations:
                setattr(profile, recommendation.dimension, recommendation.value)
                setattr(
                    profile,
                    f"{recommendation.dimension}_confidence",
                    recommendation.confidence,
                )
            await session.flush()

            history = LearnerProfileHistory(
                id=uuid.uuid4(),
                learner_profile_id=profile.id,
                learner_id=profile.learner_id,
                version=profile.version,
                observed_event_count=profile.observed_event_count,
                last_evaluated_at=profile.last_evaluated_at,
                change_source=ProfileChangeSource.SYSTEM_INFERENCE,
                changed_by=changed_by,
                change_reason=change_reason[:500],
                **_profile_dimension_values(profile),
            )
            session.add(history)
            await session.flush()
            return ProfileUpdateRecord(
                profile_id=profile.id,
                history_id=history.id,
                version=profile.version,
            )

    async def create_attention_flag(
        self,
        *,
        context: SessionProfileUpdateContext,
        flag: ProfileAttentionFlagDraft,
    ) -> UUID:
        async with self._sessions.begin() as session:
            profile = await _load_or_create_profile(session, context.student_id)
            attention_flag = LearnerProfileAttentionFlag(
                id=uuid.uuid4(),
                student_id=context.student_id,
                lesson_session_id=context.lesson_session_id,
                learner_profile_id=profile.id,
                dimension=flag.dimension,
                current_value=flag.current_value,
                recommended_value=flag.recommended_value,
                rationale=flag.rationale[:500],
                status=ProfileAttentionFlagStatus.OPEN,
            )
            session.add(attention_flag)
            await session.flush()
            return attention_flag.id


async def _load_or_create_profile(
    session: AsyncSession,
    student_id: UUID,
) -> LearnerProfile:
    profile = await session.scalar(
        select(LearnerProfile).where(LearnerProfile.learner_id == student_id)
    )
    if profile is not None:
        return profile
    profile = LearnerProfile(id=uuid.uuid4(), learner_id=student_id)
    session.add(profile)
    await session.flush()
    return profile


def _profile_for_prompt(
    current_profile: Mapping[str, ProfileDimensionState],
) -> dict[str, dict[str, str | int | None]]:
    return {
        dimension: {
            "value": _serialize_profile_value(state.value),
            "confidence": state.confidence.value,
        }
        for dimension, state in current_profile.items()
    }


def _profile_from_model(
    profile: LearnerProfile,
) -> dict[str, ProfileDimensionState]:
    return {
        dimension: ProfileDimensionState(
            value=getattr(profile, dimension),
            confidence=getattr(profile, f"{dimension}_confidence"),
        )
        for dimension in CANONICAL_PROFILE_DIMENSIONS
    }


def _empty_profile_state() -> dict[str, ProfileDimensionState]:
    return {
        dimension: ProfileDimensionState(value=None, confidence=ConfidenceLevel.LOW)
        for dimension in CANONICAL_PROFILE_DIMENSIONS
    }


def _profile_dimension_values(profile: LearnerProfile) -> dict[str, object]:
    values: dict[str, object] = {}
    for dimension in CANONICAL_PROFILE_DIMENSIONS:
        values[dimension] = getattr(profile, dimension)
        values[f"{dimension}_confidence"] = getattr(
            profile,
            f"{dimension}_confidence",
        )
    values["processing_channel_preference"] = profile.processing_channel_preference
    values["processing_channel_preference_confidence"] = (
        profile.processing_channel_preference_confidence
    )
    return values


def _session_summary(
    lesson_session: LessonSession,
    events: Iterable[SignalEvent],
) -> dict[str, object]:
    event_list = tuple(events)
    counts = Counter(event.event_type.value for event in event_list)
    return {
        "lesson_session": {
            "id": str(lesson_session.id),
            "lesson_id": str(lesson_session.lesson_id),
            "started_at": lesson_session.started_at.isoformat(),
            "ended_at": (
                lesson_session.ended_at.isoformat()
                if lesson_session.ended_at is not None
                else None
            ),
            "completion_status": lesson_session.completion_status.value,
            "exit_position": lesson_session.exit_position,
            "break_count": lesson_session.break_count,
            "proactive_adjustments_count": (
                lesson_session.proactive_adjustments_count
            ),
        },
        "event_count": len(event_list),
        "event_type_counts": dict(sorted(counts.items())),
        "events": [
            {
                "event_type": event.event_type.value,
                "timestamp": event.timestamp.isoformat(),
                "event_data": event.event_data,
            }
            for event in event_list
        ],
    }


def _json_payload(response_text: str) -> str:
    stripped = response_text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 3 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped


def _coerce_profile_value(
    dimension: str,
    value: object,
) -> int | ChannelPreferenceStrength | None:
    if value is None:
        return None
    if dimension in CHANNEL_DIMENSIONS:
        return ChannelPreferenceStrength(str(value))
    number = int(value)
    if dimension == "attention_span":
        if number < 1 or number > 240:
            raise ProfileUpdateResponseError("attention_span is out of range")
        return number
    if number < 1 or number > 5:
        raise ProfileUpdateResponseError(f"{dimension} is out of range")
    return number


def _is_significant_change(
    dimension: str,
    current_value: int | ChannelPreferenceStrength,
    recommended_value: int | ChannelPreferenceStrength,
) -> bool:
    if dimension in CHANNEL_DIMENSIONS:
        strength_order = {
            ChannelPreferenceStrength.LOW: 1,
            ChannelPreferenceStrength.MODERATE: 2,
            ChannelPreferenceStrength.STRONG: 3,
        }
        return (
            abs(
                strength_order[ChannelPreferenceStrength(str(current_value))]
                - strength_order[ChannelPreferenceStrength(str(recommended_value))]
            )
            >= 2
        )
    if dimension == "attention_span":
        return abs(int(current_value) - int(recommended_value)) >= 60
    return abs(int(current_value) - int(recommended_value)) >= 2


def _serialize_profile_value(
    value: int | ChannelPreferenceStrength | None,
) -> str | int | None:
    if isinstance(value, ChannelPreferenceStrength):
        return value.value
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
