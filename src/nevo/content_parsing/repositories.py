from collections.abc import Sequence
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.content_parsing.entities import (
    ContentParseRequest,
    ParsedLesson,
    ParsedLessonSegment,
    StoredParsedLesson,
)
from nevo.db.models.account import User
from nevo.db.models.content import ContentParseRun, Lesson, LessonSegment
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

    async def store(
        self,
        *,
        request: ContentParseRequest,
        parsed: ParsedLesson,
        requested_by_user_id: UUID,
    ) -> StoredParsedLesson:
        lesson_id = uuid4()
        parse_run_id = uuid4()
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
            session.add(
                Lesson(
                    id=lesson_id,
                    school_id=school_id,
                    created_by_user_id=requested_by_user_id,
                    title=parsed.title,
                    source_type=request.source_type,
                    source_reference=request.source_metadata,
                    parser_version=1,
                    status=status,
                    segment_count=len(parsed.segments),
                    review_segment_count=review_segment_count,
                    confirmation_summary=parsed.confirmation_summary,
                )
            )
            session.add(
                ContentParseRun(
                    id=parse_run_id,
                    lesson_id=lesson_id,
                    requested_by_user_id=requested_by_user_id,
                    status=status,
                    source_type=request.source_type,
                    source_metadata=request.source_metadata,
                    chunk_count=parsed.chunk_count,
                    gemini_call_count=parsed.gemini_call_count,
                    calculation_segment_count=calculation_segment_count,
                    tts_call_count=tts_call_count,
                    review_notes=list(parsed.review_notes),
                )
            )
            for segment in parsed.segments:
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
                        comprehension_checkpoints=list(
                            segment.comprehension_checkpoints
                        ),
                        text_variant=segment.text_variant,
                        visual_variant=segment.visual_variant,
                        audio_variant=segment.audio_variant,
                        interactive_variant=segment.interactive_variant,
                        calculation_variant=segment.calculation_variant,
                        needs_review=segment.needs_review,
                        review_reasons=list(segment.review_reasons),
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
