from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.signal_event import LessonSession, SignalEvent
from nevo.domain.signal_events.vocabulary import (
    LessonCompletionStatus,
    SignalEventType,
)
from nevo.intelligence.entities import BehaviourPatternAggregate


class SqlAlchemyAccommodationPatternRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def aggregate_for_student(
        self,
        *,
        student_id: UUID,
        lesson_limit: int = 5,
    ) -> BehaviourPatternAggregate:
        async with self._sessions() as session:
            lesson_sessions = (
                await session.scalars(
                    select(LessonSession)
                    .where(
                        LessonSession.student_id == student_id,
                        LessonSession.completion_status
                        == LessonCompletionStatus.COMPLETED,
                    )
                    .order_by(LessonSession.started_at.desc())
                    .limit(lesson_limit)
                )
            ).all()
            if not lesson_sessions:
                return BehaviourPatternAggregate(lesson_count=0)
            session_ids = [lesson.id for lesson in lesson_sessions]
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

        evidence_by_session: dict[UUID, set[str]] = defaultdict(set)
        maths_sessions: set[UUID] = set()
        for event in events:
            evidence = _evidence_from_event(event)
            evidence_by_session[event.session_id].update(evidence)
            if _is_maths_event(event):
                maths_sessions.add(event.session_id)

        return BehaviourPatternAggregate(
            lesson_count=len(lesson_sessions),
            reading_latency_lessons=_count(evidence_by_session, "reading_latency"),
            backward_scroll_lessons=_count(evidence_by_session, "backward_scroll"),
            word_pause_lessons=_count(evidence_by_session, "word_pause"),
            low_text_completion_lessons=_count(evidence_by_session, "low_text_completion"),
            task_switch_lessons=_count(evidence_by_session, "task_switch"),
            erratic_navigation_lessons=_count(evidence_by_session, "erratic_navigation"),
            focus_drop_lessons=_count(evidence_by_session, "focus_drop"),
            fragmented_flow_lessons=_count(evidence_by_session, "fragmented_flow"),
            maths_lesson_count=len(maths_sessions),
            calculation_latency_lessons=_count(evidence_by_session, "calculation_latency"),
            numerical_correction_lessons=_count(
                evidence_by_session,
                "numerical_correction",
            ),
            repeated_numeric_mistake_lessons=_count(
                evidence_by_session,
                "repeated_numeric_mistake",
            ),
            numeric_hesitation_lessons=_count(evidence_by_session, "numeric_hesitation"),
        )


def _count(evidence_by_session: dict[UUID, set[str]], key: str) -> int:
    return sum(1 for evidence in evidence_by_session.values() if key in evidence)


def _evidence_from_event(event: SignalEvent) -> set[str]:
    data = event.event_data or {}
    evidence = set()
    if _reading_latency_high(event, data):
        evidence.add("reading_latency")
    if _number(data, "backwardScrollCount") >= 2 or data.get("direction") == "backward":
        evidence.add("backward_scroll")
    if _number(data, "wordPauseMs") >= 1_500 or data.get("longWordPause") is True:
        evidence.add("word_pause")
    if _is_text_heavy(data) and _number(data, "completionRate", default=1) <= 0.6:
        evidence.add("low_text_completion")
    if _number(data, "taskSwitchCount") >= 3:
        evidence.add("task_switch")
    if data.get("navigationPattern") == "erratic" or data.get("erraticNavigation") is True:
        evidence.add("erratic_navigation")
    if (
        _number(data, "focusDropAfterMinutes") >= 5
        or (
            _number(data, "sustainedMinutes") >= 5
            and _number(data, "engagementDropSeconds") >= 60
        )
    ):
        evidence.add("focus_drop")
    if data.get("fragmentedTaskFlow") is True or _number(data, "taskFragmentCount") >= 4:
        evidence.add("fragmented_flow")
    if _calculation_latency_high(data):
        evidence.add("calculation_latency")
    if _number(data, "numericCorrectionCount") >= 2:
        evidence.add("numerical_correction")
    if _number(data, "repeatedMistakesOnSimilarOperation") >= 2:
        evidence.add("repeated_numeric_mistake")
    if _number(data, "numericHesitationMs") >= 5_000:
        evidence.add("numeric_hesitation")
    return evidence


def _reading_latency_high(event: SignalEvent, data: dict[str, object]) -> bool:
    if not _is_text_heavy(data):
        return False
    if data.get("readingLatencyHigh") is True:
        return True
    if _number(data, "readingLatencyRatio") >= 1.5:
        return True
    if event.event_type is SignalEventType.TIME_ON_SEGMENT:
        expected_ms = _number(data, "expectedMs")
        duration_ms = _number(data, "durationMs")
        return expected_ms > 0 and duration_ms / expected_ms >= 1.5
    return _number(data, "readingLatencyMs") >= 8_000


def _calculation_latency_high(data: dict[str, object]) -> bool:
    return (
        _number(data, "calculationLatencyMs") >= 8_000
        or _number(data, "calculationLatencyRatio") >= 1.5
    )


def _is_text_heavy(data: dict[str, object]) -> bool:
    return (
        data.get("textHeavy") is True
        or data.get("contentType") in {"text_heavy", "reading", "explanatory_text"}
        or _number(data, "textDensity") >= 0.65
    )


def _is_maths_event(event: SignalEvent) -> bool:
    data = event.event_data or {}
    return (
        event.event_type
        in {
            SignalEventType.CALCULATION_STEP_RESPONSE,
            SignalEventType.CALCULATION_COMPLETE,
        }
        or data.get("contentArea") in {"math", "maths", "numerical"}
        or data.get("mathsOnly") is True
    )


def _number(data: dict[str, object], key: str, *, default: float = 0) -> float:
    try:
        return float(data.get(key, default))
    except (TypeError, ValueError):
        return default
