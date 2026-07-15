import json
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.ai_gateway.entities import AiGenerationRequest
from nevo.ai_gateway.service import AiGatewayService
from nevo.db.models.attention_flag import (
    AttentionFlag,
    Escalation,
    InterventionRecommendation,
)
from nevo.db.models.signal_event import LessonSession, SignalEvent
from nevo.domain.ai_gateway.vocabulary import AiService
from nevo.domain.attention_flags.vocabulary import AttentionFlagType
from nevo.domain.signal_events.vocabulary import SignalEventType

INTERVENTION_RECOMMENDATION_PROMPT_NAME = "intervention_recommendation.default"
STANDARD_DECLINE_MINIMUM_SESSIONS = 3
STANDARD_DECLINE_RECENT_SESSIONS = 2
STANDARD_DECLINE_THRESHOLD = 0.15
SUDDEN_CHANGE_THRESHOLD = 0.35


@dataclass(frozen=True, slots=True)
class SessionEngagementSnapshot:
    session_id: UUID
    started_at: datetime
    engagement_score: float
    event_count: int = 0


@dataclass(frozen=True, slots=True)
class AttentionFlagDraft:
    student_id: UUID
    flag_type: AttentionFlagType
    description: str
    session_ids: tuple[UUID, ...]
    baseline_score: float | None
    current_score: float | None


@dataclass(frozen=True, slots=True)
class AttentionDetectionContext:
    student_id: UUID
    sessions: tuple[SessionEngagementSnapshot, ...]


@dataclass(frozen=True, slots=True)
class AttentionFlagRecord:
    id: UUID
    student_id: UUID
    flag_type: AttentionFlagType
    description: str
    generated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class InterventionRecommendationRecord:
    id: UUID
    attention_flag_id: UUID
    student_id: UUID
    recommendation_text: str
    ai_gateway_call_id: UUID | None


@dataclass(frozen=True, slots=True)
class AttentionFlagOutcome:
    attention_flag_id: UUID | None
    recommendation_id: UUID | None
    flag_type: AttentionFlagType | None
    status: str


class AttentionFlagRepository(Protocol):
    async def load_detection_context(
        self,
        *,
        student_id: UUID,
    ) -> AttentionDetectionContext: ...

    async def create_attention_flag(
        self,
        draft: AttentionFlagDraft,
    ) -> AttentionFlagRecord: ...

    async def create_intervention_recommendation(
        self,
        *,
        attention_flag_id: UUID,
        student_id: UUID,
        recommendation_text: str,
        ai_gateway_call_id: UUID | None,
    ) -> InterventionRecommendationRecord: ...

    async def create_escalation(
        self,
        *,
        student_id: UUID,
        teacher_id: UUID,
        teacher_note: str,
        attention_flag_id: UUID | None = None,
    ) -> UUID: ...


class AttentionFlagDetectionService:
    def __init__(
        self,
        *,
        repository: AttentionFlagRepository,
        gateway: AiGatewayService,
    ) -> None:
        self._repository = repository
        self._gateway = gateway

    async def evaluate_student(
        self,
        *,
        student_id: UUID,
        requested_by_user_id: UUID,
    ) -> AttentionFlagOutcome:
        context = await self._repository.load_detection_context(
            student_id=student_id,
        )
        draft = detect_attention_flag(
            student_id=student_id,
            sessions=context.sessions,
        )
        if draft is None:
            return AttentionFlagOutcome(
                attention_flag_id=None,
                recommendation_id=None,
                flag_type=None,
                status="no_flag",
            )

        flag = await self._repository.create_attention_flag(draft)
        recommendation_text, call_id = await self._generate_recommendation(
            flag=flag,
            draft=draft,
            requested_by_user_id=requested_by_user_id,
        )
        recommendation = await self._repository.create_intervention_recommendation(
            attention_flag_id=flag.id,
            student_id=student_id,
            recommendation_text=recommendation_text,
            ai_gateway_call_id=call_id,
        )
        return AttentionFlagOutcome(
            attention_flag_id=flag.id,
            recommendation_id=recommendation.id,
            flag_type=flag.flag_type,
            status="flagged",
        )

    async def escalate_to_support(
        self,
        *,
        student_id: UUID,
        teacher_id: UUID,
        teacher_note: str,
        attention_flag_id: UUID | None = None,
    ) -> UUID:
        return await self._repository.create_escalation(
            student_id=student_id,
            teacher_id=teacher_id,
            teacher_note=teacher_note,
            attention_flag_id=attention_flag_id,
        )

    async def _generate_recommendation(
        self,
        *,
        flag: AttentionFlagRecord,
        draft: AttentionFlagDraft,
        requested_by_user_id: UUID,
    ) -> tuple[str, UUID | None]:
        result = await self._gateway.generate(
            AiGenerationRequest(
                requester_user_id=requested_by_user_id,
                student_id=flag.student_id,
                service=AiService.NARRATIVE,
                prompt_name=INTERVENTION_RECOMMENDATION_PROMPT_NAME,
                variables={
                    "flag_context": json.dumps(
                        {
                            "flag_type": flag.flag_type.value,
                            "description": flag.description,
                            "session_ids": [
                                str(session_id) for session_id in draft.session_ids
                            ],
                            "baseline_score": draft.baseline_score,
                            "current_score": draft.current_score,
                        },
                        sort_keys=True,
                    )
                },
                max_output_tokens=700,
            )
        )
        return parse_recommendation_response(result.text), result.call_id


def detect_attention_flag(
    *,
    student_id: UUID,
    sessions: Iterable[SessionEngagementSnapshot],
) -> AttentionFlagDraft | None:
    ordered_sessions = tuple(sorted(sessions, key=lambda item: item.started_at))
    if len(ordered_sessions) < 2:
        return None

    sudden_change = _detect_sudden_change(student_id, ordered_sessions)
    if sudden_change is not None:
        return sudden_change
    return _detect_engagement_decline(student_id, ordered_sessions)


def parse_recommendation_response(response_text: str) -> str:
    stripped = response_text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            stripped = "\n".join(lines[1:-1]).strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    if not isinstance(payload, dict):
        return stripped
    recommendation = payload.get("recommendation_text")
    if recommendation is None:
        return stripped
    return str(recommendation).strip()


class SqlAlchemyAttentionFlagRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def load_detection_context(
        self,
        *,
        student_id: UUID,
    ) -> AttentionDetectionContext:
        async with self._sessions() as session:
            lesson_sessions = (
                await session.scalars(
                    select(LessonSession)
                    .where(LessonSession.student_id == student_id)
                    .order_by(LessonSession.started_at.desc())
                    .limit(8)
                )
            ).all()
            ordered_sessions = tuple(
                sorted(lesson_sessions, key=lambda item: item.started_at)
            )
            session_ids = [item.id for item in ordered_sessions]
            events_by_session: dict[UUID, list[SignalEvent]] = {
                session_id: [] for session_id in session_ids
            }
            if session_ids:
                events = (
                    await session.scalars(
                        select(SignalEvent)
                        .where(
                            SignalEvent.student_id == student_id,
                            SignalEvent.session_id.in_(session_ids),
                        )
                        .order_by(SignalEvent.timestamp)
                    )
                ).all()
                for event in events:
                    events_by_session.setdefault(event.session_id, []).append(event)
            return AttentionDetectionContext(
                student_id=student_id,
                sessions=tuple(
                    SessionEngagementSnapshot(
                        session_id=lesson_session.id,
                        started_at=lesson_session.started_at,
                        engagement_score=session_engagement_score(
                            events_by_session.get(lesson_session.id, ())
                        ),
                        event_count=len(events_by_session.get(lesson_session.id, ())),
                    )
                    for lesson_session in ordered_sessions
                ),
            )

    async def create_attention_flag(
        self,
        draft: AttentionFlagDraft,
    ) -> AttentionFlagRecord:
        async with self._sessions.begin() as session:
            record = AttentionFlag(
                id=uuid.uuid4(),
                student_id=draft.student_id,
                flag_type=draft.flag_type,
                description=draft.description,
            )
            session.add(record)
            await session.flush()
            return AttentionFlagRecord(
                id=record.id,
                student_id=record.student_id,
                flag_type=record.flag_type,
                description=record.description,
                generated_at=record.generated_at,
            )

    async def create_intervention_recommendation(
        self,
        *,
        attention_flag_id: UUID,
        student_id: UUID,
        recommendation_text: str,
        ai_gateway_call_id: UUID | None,
    ) -> InterventionRecommendationRecord:
        async with self._sessions.begin() as session:
            record = InterventionRecommendation(
                id=uuid.uuid4(),
                attention_flag_id=attention_flag_id,
                student_id=student_id,
                recommendation_text=recommendation_text,
                ai_gateway_call_id=ai_gateway_call_id,
            )
            session.add(record)
            await session.flush()
            return InterventionRecommendationRecord(
                id=record.id,
                attention_flag_id=record.attention_flag_id,
                student_id=record.student_id,
                recommendation_text=record.recommendation_text,
                ai_gateway_call_id=record.ai_gateway_call_id,
            )

    async def create_escalation(
        self,
        *,
        student_id: UUID,
        teacher_id: UUID,
        teacher_note: str,
        attention_flag_id: UUID | None = None,
    ) -> UUID:
        async with self._sessions.begin() as session:
            record = Escalation(
                id=uuid.uuid4(),
                attention_flag_id=attention_flag_id,
                student_id=student_id,
                teacher_id=teacher_id,
                teacher_note=teacher_note,
            )
            session.add(record)
            await session.flush()
            return record.id


def session_engagement_score(events: Iterable[SignalEvent]) -> float:
    scores: list[float] = []
    exit_attempts = 0
    positive_events = 0
    for event in events:
        if event.event_type is SignalEventType.EXIT_ATTEMPT:
            exit_attempts += 1
        if event.event_type in {
            SignalEventType.BREAK_TAKEN,
            SignalEventType.MODALITY_SUGGESTION_ACCEPTED,
            SignalEventType.CALCULATION_COMPLETE,
        }:
            positive_events += 1
        score = _extract_engagement_score(event.event_data)
        if score is not None:
            scores.append(score)
    if scores:
        return _clamp(sum(scores) / len(scores))
    heuristic = 0.65 + min(positive_events, 3) * 0.05 - min(exit_attempts, 4) * 0.12
    return _clamp(heuristic)


def _detect_engagement_decline(
    student_id: UUID,
    sessions: tuple[SessionEngagementSnapshot, ...],
) -> AttentionFlagDraft | None:
    if len(sessions) < STANDARD_DECLINE_MINIMUM_SESSIONS:
        return None
    recent = sessions[-STANDARD_DECLINE_RECENT_SESSIONS:]
    baseline_sessions = sessions[:-STANDARD_DECLINE_RECENT_SESSIONS]
    if not baseline_sessions:
        return None
    baseline = _average_score(baseline_sessions)
    if all(
        session.engagement_score <= baseline - STANDARD_DECLINE_THRESHOLD
        for session in recent
    ):
        current_score = _average_score(recent)
        return AttentionFlagDraft(
            student_id=student_id,
            flag_type=AttentionFlagType.ENGAGEMENT_DECLINE,
            description=(
                "Engagement signals have remained below this student's recent "
                "baseline across two consecutive sessions."
            ),
            session_ids=tuple(session.session_id for session in recent),
            baseline_score=round(baseline, 3),
            current_score=round(current_score, 3),
        )
    return None


def _detect_sudden_change(
    student_id: UUID,
    sessions: tuple[SessionEngagementSnapshot, ...],
) -> AttentionFlagDraft | None:
    latest = sessions[-1]
    baseline_sessions = sessions[:-1]
    if not baseline_sessions:
        return None
    baseline = _average_score(baseline_sessions)
    if latest.engagement_score <= baseline - SUDDEN_CHANGE_THRESHOLD:
        return AttentionFlagDraft(
            student_id=student_id,
            flag_type=AttentionFlagType.SUDDEN_CHANGE,
            description=(
                "The most recent session diverged sharply from this student's "
                "usual engagement pattern and may need timely teacher review."
            ),
            session_ids=(latest.session_id,),
            baseline_score=round(baseline, 3),
            current_score=round(latest.engagement_score, 3),
        )
    return None


def _extract_engagement_score(event_data: Mapping[str, object]) -> float | None:
    for key in (
        "engagementScore",
        "engagement_score",
        "engagement",
        "score",
        "value",
    ):
        value = event_data.get(key)
        if isinstance(value, int | float):
            return _normalize_score(float(value))
        if isinstance(value, str):
            try:
                return _normalize_score(float(value))
            except ValueError:
                continue
    return None


def _normalize_score(score: float) -> float:
    if score > 1:
        score = score / 100
    return _clamp(score)


def _average_score(sessions: Iterable[SessionEngagementSnapshot]) -> float:
    scores = [session.engagement_score for session in sessions]
    return sum(scores) / len(scores)


def _clamp(score: float) -> float:
    return max(0, min(score, 1))
