from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from nevo.intelligence.accommodation_repositories import SqlAlchemyAccommodationPatternRepository
from nevo.intelligence.accommodations import UdlAccommodationInferenceEngine


async def lesson_delivery_config(session, student, lesson_id):
    from nevo.db.models.signal_event import LessonSession

    sitting = await session.scalar(
        select(LessonSession)
        .where(
            LessonSession.student_id == student.id,
            LessonSession.lesson_id == lesson_id,
            LessonSession.completion_status == "in_progress",
            LessonSession.ended_at.is_(None),
        )
        .order_by(LessonSession.started_at.desc())
        .limit(1)
    )
    return (
        ((sitting.delivery_state or {}).get("engineConfig") if sitting else None)
        or student.engine_config
        or {}
    )


async def delivery_snapshot(session, student, lesson_session=None):
    """Freeze only session delivery, never an accommodation label on a user."""
    from nevo.api.response_models import EngineConfig

    if lesson_session is not None and lesson_session.delivery_state:
        return dict(lesson_session.delivery_state)
    aggregate = await SqlAlchemyAccommodationPatternRepository(
        async_sessionmaker(session.bind, expire_on_commit=False)
    ).aggregate_for_student(student_id=student.id)
    analysis = UdlAccommodationInferenceEngine().analyse(student_id=student.id, aggregate=aggregate)
    active = [signal.accommodation.value for signal in analysis.active]
    config = EngineConfig.model_validate(student.engine_config or {})
    config.support.number_problems_step_by_step = (
        config.support.number_problems_step_by_step or "numerical" in active
    )
    config.support.numerical_visuals = config.support.numerical_visuals or "numerical" in active
    config.support.shorter_text_blocks = config.support.shorter_text_blocks or bool(
        {"reading", "attention"} & set(active)
    )
    config.support.pause_between_segments = (
        config.support.pause_between_segments or "attention" in active
    )
    if "reading" in active:
        config.reading.font_scale = 1.15
        config.reading.line_spacing = 1.8
        config.reading.contrast = "soft"
    if lesson_session is not None and lesson_session.delivery_depth == "lower":
        from nevo.domain.intelligence.vocabulary import ScaffoldingLevel

        config.support.initial_scaffold_level = ScaffoldingLevel.STRONG
        config.support.shorter_text_blocks = True
        config.support.pause_between_segments = True
        config.reading.segment_word_target = min(80, config.reading.segment_word_target)
    snapshot = {
        "engineConfig": config.model_dump(by_alias=True, mode="json"),
        "accommodations": active,
        "capturedAt": datetime.now(UTC).isoformat(),
        "accommodationEvidence": [
            {
                "accommodation": signal.accommodation.value,
                "frontendSignal": signal.frontend_signal,
                "evidence": list(signal.evidence),
                "lessonCount": signal.lesson_count,
            }
            for signal in analysis.active
        ],
    }
    if lesson_session is not None:
        lesson_session.delivery_state = snapshot
    return snapshot
