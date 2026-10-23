import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from nevo.api.lesson_contracts import UnclassifiableQuestionError, checkpoint_payloads
from nevo.api.product_learning import UploadRequest, staged_upload
from nevo.auth.entities import AuthPrincipal
from nevo.content_parsing.entities import ContentParseRequest, ParsedLesson, ParsedLessonSegment
from nevo.content_parsing.repositories import SqlAlchemyContentParsingRepository
from nevo.content_parsing.upload_reuse import find_reusable_upload, source_key
from nevo.db.models.media_usage import media_usage_events
from nevo.db.models.product import UploadJob, UploadSourceBlob
from nevo.domain.intelligence.vocabulary import ContentModality, LessonContentType, LessonSourceType
from tests.content_parsing.test_checkpoint_storage_runtime import URL, setup


@pytest.mark.parametrize(
    "key,kind", [("a", "single_choice"), (["a"], "single_choice"), (["a", "b"], "multiple_choice")]
)
def test_selection_is_classified_from_its_actual_answer(key, kind):
    result = checkpoint_payloads(
        [
            {
                "prompt": "Choose",
                "answerType": "selection",
                "answerKey": key,
                "options": [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}],
            }
        ],
        segment_key="one",
        strict=True,
    )[0]
    assert result["answerType"] == kind


def test_unknown_or_unmarkable_question_is_still_refused():
    for kind, key in (("unknown_renderer", "a"), ("selection", "not-an-option")):
        with pytest.raises(UnclassifiableQuestionError):
            checkpoint_payloads(
                [
                    {
                        "prompt": "Choose",
                        "answerType": kind,
                        "answerKey": key,
                        "options": ["a", "b"],
                    }
                ],
                segment_key="one",
                strict=True,
            )


@pytest.mark.skipif(not URL, reason="Disposable database required")
def test_unchanged_upload_reuses_prepared_lesson_and_counts_media(monkeypatch):
    async def scenario():
        engine, sessions, teacher, school = await setup()
        try:
            parsed = await SqlAlchemyContentParsingRepository(sessions).store(
                request=ContentParseRequest(title="Forces", source_type=LessonSourceType.TEXT),
                parsed=ParsedLesson(
                    title="Forces",
                    segments=(
                        ParsedLessonSegment(
                            segment_key="one",
                            content_type=LessonContentType.EXPLANATORY_TEXT,
                            sequence_order=1,
                            title="Forces",
                            body="A force is a push or pull.",
                            available_modalities=(ContentModality.TEXT, ContentModality.AUDIO),
                            audio_variant={
                                "script": "A force is a push or pull.",
                                "audioUrl": "https://example.org/audio.mp3",
                                "storagePath": "audio/test.mp3",
                                "provider": "yarngpt",
                            },
                        ),
                    ),
                ),
                requested_by_user_id=teacher,
            )
            payload = UploadRequest(
                title="Forces",
                filename="forces.txt",
                sourceType="text",
                sourceText="A force is a push or pull.",
            )
            key = source_key(
                text=payload.source_text,
                title=payload.title,
                subject=None,
                source_type="text",
                scope="lesson",
            )
            async with sessions.begin() as session:
                job = UploadJob(
                    school_id=school,
                    requested_by_id=teacher,
                    filename="forces.txt",
                    scope="lesson",
                    status="ready",
                    stage="ready_to_assign",
                    structure={"lessonId": str(parsed.lesson_id), "sourceCacheKey": key},
                )
                session.add(job)
                await session.flush()
                job_id = job.id
                session.add(
                    UploadSourceBlob(
                        upload_id=job.id,
                        filename="forces.txt",
                        content_type="text/plain",
                        content=b"same bytes",
                    )
                )
            monkeypatch.setattr(
                "nevo.api.product_learning._parse_into_job",
                AsyncMock(side_effect=AssertionError("Must not invoke the parser")),
            )
            async with sessions() as session:
                result = await staged_upload(
                    payload, AuthPrincipal(teacher, "teacher", uuid4()), session, None, sessions
                )
                assert result["reused"] is True and result["uploadId"] == str(job_id)
                for content, subject, actor in (
                    (b"different", None, teacher),
                    (b"same bytes", "Biology", teacher),
                    (b"same bytes", None, uuid4()),
                ):
                    assert (
                        await find_reusable_upload(
                            session,
                            actor_id=actor,
                            school_id=school,
                            scope="lesson",
                            content=content,
                            subject=subject,
                        )
                        is None
                    )
                assert (
                    await find_reusable_upload(
                        session,
                        actor_id=teacher,
                        school_id=school,
                        scope="lesson",
                        content=b"same bytes",
                    )
                    is not None
                )
            async with sessions() as session:
                rows = (
                    (
                        await session.execute(
                            select(media_usage_events).where(
                                media_usage_events.c.asset_path == "audio/test.mp3",
                                media_usage_events.c.status == "cache_hit",
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                assert rows and rows[-1]["asset_path"] == "audio/test.mp3"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.skipif(not URL, reason="Disposable database required")
def test_repeat_upload_reuses_an_in_flight_job_without_new_generation(monkeypatch):
    async def scenario():
        engine, sessions, teacher, school = await setup()
        try:
            payload = UploadRequest(
                title="Respiration",
                filename="respiration.txt",
                sourceType="text",
                sourceText="Cells release usable energy.",
            )
            key = source_key(
                text=payload.source_text,
                title=payload.title,
                subject=None,
                source_type="text",
                scope="lesson",
            )
            async with sessions.begin() as session:
                job = UploadJob(
                    school_id=school,
                    requested_by_id=teacher,
                    scope="lesson",
                    filename="respiration.txt",
                    status="processing",
                    stage="preparing_adaptations",
                    structure={"sourceCacheKey": key},
                )
                session.add(job)
                await session.flush()
                job_id = job.id
            monkeypatch.setattr(
                "nevo.api.product_learning._parse_into_job",
                AsyncMock(side_effect=AssertionError("Duplicate generation")),
            )
            async with sessions() as session:
                response = await staged_upload(
                    payload, AuthPrincipal(teacher, "teacher", uuid4()), session, None, sessions
                )
                assert response["uploadId"] == str(job_id)
                assert response["status"] == "processing"
                assert response["reused"] is True
        finally:
            await engine.dispose()

    asyncio.run(scenario())
