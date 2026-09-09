from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.api.lesson_contracts import checkpoint_payloads
from nevo.content_parsing.entities import (
    ContentParseRequest,
    ParsedLesson,
    ParsedLessonSegment,
    ParseRunState,
    StoredParsedLesson,
)
from nevo.db.models.account import User
from nevo.db.models.content import ContentParseRun, Lesson, LessonSegment
from nevo.db.models.frontend_support import Concept
from nevo.domain.accounts.vocabulary import UserStatus
from nevo.domain.intelligence.vocabulary import (
    ContentModality,
    ContentParseStatus,
    LessonContentType,
)


class SqlAlchemyContentParsingRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def requester_school_id(self, user_id: UUID) -> UUID | None:
        async with self._sessions() as session:
            return await session.scalar(
                select(User.school_id).where(
                    User.id == user_id,
                    User.status != UserStatus.DEACTIVATED,
                )
            )

    async def begin_run(
        self,
        *,
        request: ContentParseRequest,
        requested_by_user_id: UUID,
        existing_lesson_id: UUID | None = None,
    ) -> tuple[UUID, UUID]:
        """Record that a parse has started, before any of it is done.

        The run row used to be written only once the whole pipeline finished,
        which is why a call that was still working looked identical to one
        that had died: there was nothing to look at either way. Creating it up
        front is what makes the work observable.

        Returns ``(lesson_id, parse_run_id)``.
        """
        school_id = await self.requester_school_id(requested_by_user_id)
        lesson_id = existing_lesson_id or uuid4()
        parse_run_id = uuid4()
        async with self._sessions.begin() as session:
            if existing_lesson_id is None:
                session.add(
                    Lesson(
                        id=lesson_id,
                        school_id=school_id,
                        created_by_user_id=requested_by_user_id,
                        title=request.title,
                        subject=(
                            str(request.source_metadata["subject"])
                            if request.source_metadata.get("subject")
                            else None
                        ),
                        source_type=request.source_type,
                        source_reference=request.source_metadata,
                        parser_version=1,
                        status=ContentParseStatus.PROCESSING,
                        segment_count=0,
                        review_segment_count=0,
                        estimated_minutes=0,
                        confirmation_summary=None,
                    )
                )
            else:
                lesson = await session.get(Lesson, existing_lesson_id)
                if lesson is None or lesson.school_id != school_id:
                    raise ValueError("lesson is not available to this school")
            await session.flush()
            session.add(
                ContentParseRun(
                    id=parse_run_id,
                    lesson_id=lesson_id,
                    requested_by_user_id=requested_by_user_id,
                    status=ContentParseStatus.PROCESSING,
                    source_type=request.source_type,
                    source_metadata=request.source_metadata,
                    chunk_count=1,
                    gemini_call_count=0,
                    calculation_segment_count=0,
                    tts_call_count=0,
                    review_notes=[],
                )
            )
        return lesson_id, parse_run_id

    async def fail_run(self, parse_run_id: UUID, *, reason: str) -> None:
        """Say why a run stopped, rather than leaving it processing forever."""
        async with self._sessions.begin() as session:
            run = await session.get(ContentParseRun, parse_run_id)
            if run is None:
                return
            run.status = ContentParseStatus.FAILED
            run.error_message = reason[:2000]
            run.completed_at = datetime.now(UTC)
            lesson = await session.get(Lesson, run.lesson_id)
            if lesson is not None and lesson.status is ContentParseStatus.PROCESSING:
                lesson.status = ContentParseStatus.FAILED

    async def fail_stale_runs(self, *, older_than: timedelta) -> int:
        """Close out runs whose worker went away.

        A parse runs in the process that accepted it, so a deploy or a crash
        mid-run leaves a row saying "processing" that nothing will ever
        finish. A client polling that row would wait for ever.
        """
        cutoff = datetime.now(UTC) - older_than
        async with self._sessions.begin() as session:
            runs = list(
                await session.scalars(
                    select(ContentParseRun).where(
                        ContentParseRun.status == ContentParseStatus.PROCESSING,
                        ContentParseRun.created_at < cutoff,
                    )
                )
            )
            for run in runs:
                run.status = ContentParseStatus.FAILED
                run.completed_at = datetime.now(UTC)
                run.error_message = (
                    "The parse did not finish. It was most likely interrupted by a "
                    "restart; start it again."
                )
                lesson = await session.get(Lesson, run.lesson_id)
                if lesson is not None and lesson.status is ContentParseStatus.PROCESSING:
                    lesson.status = ContentParseStatus.FAILED
        return len(runs)

    async def run_state(self, parse_run_id: UUID) -> ParseRunState | None:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(ContentParseRun, Lesson.school_id)
                    .join(Lesson, Lesson.id == ContentParseRun.lesson_id)
                    .where(ContentParseRun.id == parse_run_id)
                )
            ).first()
        if row is None:
            return None
        run, school_id = row
        async with self._sessions() as session:
            segments = list(
                await session.scalars(
                    select(LessonSegment.review_reasons).where(
                        LessonSegment.parse_run_id == run.id
                    )
                )
            )
        fallback_segments = sum(
            1 for reasons in segments if "deterministic_parse_used" in (reasons or [])
        )
        return ParseRunState(
            parse_run_id=run.id,
            lesson_id=run.lesson_id,
            school_id=school_id,
            status=run.status,
            requested_by_user_id=run.requested_by_user_id,
            started_at=run.created_at,
            completed_at=run.completed_at,
            failure_reason=run.error_message,
            review_notes=tuple(run.review_notes or ()),
            segment_count=len(segments),
            fallback_segment_count=fallback_segments,
        )

    async def store(
        self,
        *,
        request: ContentParseRequest,
        parsed: ParsedLesson,
        requested_by_user_id: UUID,
        existing_lesson_id: UUID | None = None,
        parse_run_id: UUID | None = None,
    ) -> StoredParsedLesson:
        lesson_id = existing_lesson_id or uuid4()
        parse_run_id = parse_run_id or uuid4()
        school_id = await self.requester_school_id(requested_by_user_id)
        review_segment_count = sum(1 for segment in parsed.segments if segment.needs_review)
        status = (
            ContentParseStatus.COMPLETED_WITH_REVIEW
            if review_segment_count or parsed.review_notes
            else ContentParseStatus.COMPLETED
        )
        calculation_segment_count = sum(
            1
            for segment in parsed.segments
            if segment.content_type is LessonContentType.CALCULATION
        )
        tts_call_count = _count_tts_calls(parsed.segments)
        async with self._sessions.begin() as session:
            if existing_lesson_id is None:
                session.add(
                    Lesson(
                        id=lesson_id,
                        school_id=school_id,
                        created_by_user_id=requested_by_user_id,
                        title=parsed.title,
                        subject=(
                            str(request.source_metadata["subject"])
                            if request.source_metadata.get("subject")
                            else None
                        ),
                        source_type=request.source_type,
                        source_reference=request.source_metadata,
                        parser_version=1,
                        status=status,
                        segment_count=len(parsed.segments),
                        review_segment_count=review_segment_count,
                        estimated_minutes=sum(
                            segment.estimated_minutes for segment in parsed.segments
                        ),
                        confirmation_summary=parsed.confirmation_summary,
                    )
                )
            else:
                lesson = await session.get(Lesson, existing_lesson_id)
                if lesson is None or lesson.school_id != school_id:
                    raise ValueError("lesson is not available to this school")
                lesson.title = parsed.title
                lesson.subject = (
                    str(request.source_metadata["subject"])
                    if request.source_metadata.get("subject")
                    else lesson.subject
                )
                lesson.source_type = request.source_type
                lesson.source_reference = request.source_metadata
                lesson.parser_version += 1
                lesson.status = status
                lesson.segment_count = len(parsed.segments)
                lesson.review_segment_count = review_segment_count
                lesson.estimated_minutes = sum(
                    segment.estimated_minutes for segment in parsed.segments
                )
                lesson.confirmation_summary = parsed.confirmation_summary
                await session.execute(
                    delete(LessonSegment).where(LessonSegment.lesson_id == lesson_id)
                )
            await session.flush()
            run = await session.get(ContentParseRun, parse_run_id)
            if run is None:
                run = ContentParseRun(
                    id=parse_run_id,
                    lesson_id=lesson_id,
                    requested_by_user_id=requested_by_user_id,
                    source_type=request.source_type,
                    source_metadata=request.source_metadata,
                )
                session.add(run)
            run.status = status
            run.completed_at = datetime.now(UTC)
            run.error_message = None
            run.chunk_count = parsed.chunk_count
            run.gemini_call_count = parsed.gemini_call_count
            run.calculation_segment_count = calculation_segment_count
            run.tts_call_count = tts_call_count
            run.review_notes = list(parsed.review_notes)
            await session.flush()
            for segment in parsed.segments:
                checkpoints: list[dict[str, object]] = []
                for index, checkpoint in enumerate(segment.comprehension_checkpoints, start=1):
                    concept_name = str(
                        checkpoint.get("conceptName") or segment.title or parsed.title
                    ).strip()
                    concept = await session.scalar(
                        select(Concept).where(
                            Concept.school_id == school_id,
                            Concept.name == concept_name,
                            Concept.subject
                            == (
                                str(request.source_metadata.get("subject"))
                                if request.source_metadata.get("subject")
                                else None
                            ),
                        )
                    )
                    if concept is None:
                        concept = Concept(
                            school_id=school_id,
                            lesson_id=lesson_id,
                            name=concept_name,
                            subject=(
                                str(request.source_metadata.get("subject"))
                                if request.source_metadata.get("subject")
                                else None
                            ),
                            source="lesson_parser",
                        )
                        session.add(concept)
                        await session.flush()
                    elif concept.lesson_id is None:
                        concept.lesson_id = lesson_id
                    normalized = checkpoint_payloads(
                        [checkpoint],
                        segment_key=f"{segment.segment_key}-{index}",
                        concept_id=concept.id,
                    )
                    checkpoints.extend(normalized)
                session.add(
                    LessonSegment(
                        lesson_id=lesson_id,
                        parse_run_id=parse_run_id,
                        segment_key=segment.segment_key,
                        content_type=segment.content_type,
                        sequence_order=segment.sequence_order,
                        title=segment.title,
                        body=segment.body,
                        available_modalities=[
                            modality.value for modality in segment.available_modalities
                        ],
                        comprehension_checkpoints=checkpoints,
                        text_variant=segment.text_variant,
                        visual_variant=segment.visual_variant,
                        audio_variant=segment.audio_variant,
                        interactive_variant=segment.interactive_variant,
                        calculation_variant=segment.calculation_variant,
                        needs_review=segment.needs_review,
                        review_reasons=list(segment.review_reasons),
                        estimated_minutes=segment.estimated_minutes,
                    )
                )
        return StoredParsedLesson(
            lesson_id=lesson_id,
            parse_run_id=parse_run_id,
            status=status,
            title=parsed.title,
            segment_count=len(parsed.segments),
            review_segment_count=review_segment_count,
            confirmation_summary=parsed.confirmation_summary,
            review_notes=parsed.review_notes,
            segments=parsed.segments,
        )


def _count_tts_calls(segments: Sequence[ParsedLessonSegment]) -> int:
    calls = 0
    for segment in segments:
        if segment.audio_variant is not None:
            calls += 1
        if segment.calculation_variant is None:
            continue
        steps = segment.calculation_variant.get("steps")
        if isinstance(steps, list):
            calls += len(steps)
    return calls


def modalities_from_values(values: Sequence[str]) -> tuple[ContentModality, ...]:
    return tuple(ContentModality(value) for value in values)
