from collections import defaultdict
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.account import User
from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.models.product import LessonQuestionAttempt
from nevo.db.models.signal_event import LessonSession, SignalEvent
from nevo.domain.intelligence.vocabulary import AccommodationType
from nevo.domain.signal_events.vocabulary import (
    LessonCompletionStatus,
    SignalEventType,
)
from nevo.intelligence.entities import (
    AccommodationAnalysis,
    AccommodationSignal,
    BehaviourPatternAggregate,
)


class SqlAlchemyAccommodationPatternRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def current_session_analysis(self, *, student_id: UUID) -> AccommodationAnalysis | None:
        async with self._sessions() as session:
            sitting = await session.scalar(
                select(LessonSession)
                .where(
                    LessonSession.student_id == student_id,
                    LessonSession.completion_status == LessonCompletionStatus.IN_PROGRESS,
                    LessonSession.lesson_id.is_not(None),
                )
                .order_by(LessonSession.started_at.desc())
                .limit(1)
            )
            if sitting is None or not sitting.delivery_state:
                return None
            return AccommodationAnalysis(
                student_id=student_id,
                source="session_delivery_snapshot",
                active=tuple(
                    AccommodationSignal(
                        accommodation=AccommodationType(item["accommodation"]),
                        frontend_signal=item["frontendSignal"],
                        evidence=tuple(item["evidence"]),
                        lesson_count=item["lessonCount"],
                    )
                    for item in sitting.delivery_state.get("accommodationEvidence", [])
                ),
            )

    async def aggregate_for_student(
        self,
        *,
        student_id: UUID,
        lesson_limit: int = 5,
    ) -> BehaviourPatternAggregate:
        async with self._sessions() as session:
            latest = (
                select(
                    LessonSession.id,
                    func.row_number()
                    .over(
                        partition_by=LessonSession.lesson_id,
                        order_by=LessonSession.started_at.desc(),
                    )
                    .label("sitting"),
                )
                .where(
                    LessonSession.student_id == student_id,
                    LessonSession.lesson_id.is_not(None),
                    LessonSession.completion_status == LessonCompletionStatus.COMPLETED,
                )
                .subquery()
            )
            lesson_sessions = (
                await session.scalars(
                    select(LessonSession)
                    .join(latest, latest.c.id == LessonSession.id)
                    .where(
                        latest.c.sitting == 1,
                        LessonSession.student_id == student_id,
                        LessonSession.completion_status == LessonCompletionStatus.COMPLETED,
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
            attempts = list(
                await session.scalars(
                    select(LessonQuestionAttempt).where(
                        LessonQuestionAttempt.student_id == student_id,
                        LessonQuestionAttempt.session_id.in_(session_ids),
                    )
                )
            )
            student = await session.get(User, student_id)
            lessons = {
                row.id: row
                for row in await session.scalars(
                    select(Lesson).where(
                        Lesson.id.in_([item.lesson_id for item in lesson_sessions])
                    )
                )
            }
            segments = {
                str(row.id): row
                for row in await session.scalars(
                    select(LessonSegment).where(LessonSegment.lesson_id.in_(lessons))
                )
            }

        evidence_by_session: dict[UUID, set[str]] = defaultdict(set)
        maths_sessions: set[UUID] = set()
        for sitting in lesson_sessions:
            lesson = lessons.get(sitting.lesson_id)
            if (
                lesson
                and lesson.subject
                and any(
                    word in lesson.subject.casefold() for word in ("math", "arithmetic", "numeracy")
                )
            ):
                maths_sessions.add(sitting.id)
        positions = {}
        regressions = defaultdict(int)
        sittings_by_id = {item.id: item for item in lesson_sessions}
        segment_keys = {(row.lesson_id, row.segment_key): row for row in segments.values()}
        for event in events:
            data = event.event_data or {}
            sitting = sittings_by_id.get(event.session_id)
            segment = segments.get(str(data.get("segmentId"))) or segment_keys.get(
                (sitting.lesson_id if sitting else None, data.get("segmentId"))
            )
            key = (event.session_id, str(segment.id) if segment else str(data.get("segmentId")))
            if event.event_type in {
                SignalEventType.SCROLL,
                SignalEventType.TIME_ON_SEGMENT,
            } and isinstance(data.get("depthRatio"), (int, float)):
                position = float(data["depthRatio"])
                if key in positions and position < positions[key] - 0.1:
                    regressions[key] += 1
                positions[key] = position
                if regressions[key] >= 2:
                    evidence_by_session[event.session_id].add("backward_scroll")
            if (
                event.event_type is SignalEventType.TIME_ON_SEGMENT
                and segment
                and len(segment.body.split()) >= 80
            ):
                snapshot = sitting.delivery_state if sitting else {}
                rate = (
                    snapshot.get("engineConfig", {})
                    .get("reading", {})
                    .get("targetWordsPerMinute", 120)
                )
                expected_ms = len(segment.body.split()) * 60_000 / max(30, float(rate))
                if _number(data, "durationMs") >= expected_ms * 1.5:
                    evidence_by_session[event.session_id].add("reading_latency")
            if event.event_type is SignalEventType.ENGAGEMENT_SIGNAL:
                indicator, value = data.get("indicator"), _number(data, "value")
                if indicator == "task_switch" and value >= 3:
                    evidence_by_session[event.session_id].add("task_switch")
                if indicator == "navigation_fragmentation" and value >= 4:
                    evidence_by_session[event.session_id].update(
                        {"erratic_navigation", "fragmented_flow"}
                    )
                if (
                    indicator == "focus_drop"
                    and value >= 60_000
                    and sitting
                    and (event.timestamp - sitting.started_at).total_seconds() >= 300
                ):
                    evidence_by_session[event.session_id].add("focus_drop")
        for (sitting_id, segment_id), position in positions.items():
            segment = segments.get(segment_id)
            if segment and len(segment.body.split()) >= 80 and position <= 0.6:
                evidence_by_session[sitting_id].add("low_text_completion")
        numeric_by_question = defaultdict(list)
        baseline_ms = (student.baseline_profile or {}).get("response_time_ms") if student else None
        for attempt in attempts:
            question = attempt.question_snapshot or {}
            if attempt.source == "calculation" or question.get("answerType") == "numeric":
                maths_sessions.add(attempt.session_id)
                numeric_by_question[(attempt.session_id, attempt.question_id)].append(attempt)
                if (
                    baseline_ms
                    and attempt.response_time_ms
                    and attempt.response_time_ms >= float(baseline_ms) * 1.5
                ):
                    evidence_by_session[attempt.session_id].add("calculation_latency")
                if (
                    baseline_ms
                    and attempt.response_time_ms
                    and attempt.response_time_ms >= float(baseline_ms) + 5000
                ):
                    evidence_by_session[attempt.session_id].add("numeric_hesitation")
        for (sitting_id, _), rows in numeric_by_question.items():
            if sum(row.correct is False for row in rows) >= 2:
                evidence_by_session[sitting_id].update(
                    {"repeated_numeric_mistake", "numerical_correction"}
                )
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
    if _number(data, "focusDropAfterMinutes") >= 5 or (
        _number(data, "sustainedMinutes") >= 5 and _number(data, "engagementDropSeconds") >= 60
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
