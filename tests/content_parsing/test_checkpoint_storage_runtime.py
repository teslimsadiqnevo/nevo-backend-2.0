"""Checkpoint identifiers and interrupted staged jobs on disposable PostgreSQL."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nevo.api.lesson_contracts import checkpoint_payloads
from nevo.content_parsing.entities import ContentParseRequest, ParsedLesson
from nevo.content_parsing.repositories import SqlAlchemyContentParsingRepository
from nevo.content_parsing.service import _segment_from_payload
from nevo.db.models.account import School, User
from nevo.db.models.content import LessonSegment
from nevo.db.models.frontend_support import Concept
from nevo.db.models.product import UploadJob
from nevo.domain.intelligence.vocabulary import LessonSourceType

URL = os.getenv("NEVO_RUNTIME_TEST_DATABASE_URL", "")


def test_null_checkpoint_concept_uses_server_fallback():
    concept_id = uuid4()
    checkpoint = checkpoint_payloads(
        [{"prompt": "What is a force?", "conceptId": None}],
        segment_key="forces",
        concept_id=concept_id,
    )[0]
    assert checkpoint["conceptId"] == str(concept_id)


@pytest.mark.skipif(not URL, reason="Disposable database required")
@pytest.mark.parametrize("provided", [None, "invented-concept", str(uuid4())])
def test_actual_parse_storage_binds_checkpoint_to_real_concept(provided):
    async def scenario():
        engine, sessions, teacher_id, school_id = await setup()
        segment = _segment_from_payload(
            {
                "body": "A force is a push or a pull.",
                "title": "Forces",
                "comprehension_checkpoints": [
                    {
                        "prompt": "What is a force?",
                        "conceptId": provided,
                        "conceptName": "Forces",
                        "options": ["A push", "A colour"],
                        "answerKey": "A push",
                    }
                ],
            },
            sequence_order=1,
        )
        result = await SqlAlchemyContentParsingRepository(sessions).store(
            request=ContentParseRequest(title="Forces", source_type=LessonSourceType.TEXT),
            parsed=ParsedLesson(title="Forces", segments=(segment,)),
            requested_by_user_id=teacher_id,
        )
        async with sessions() as session:
            stored = await session.scalar(
                select(LessonSegment).where(LessonSegment.lesson_id == result.lesson_id)
            )
            concept = await session.get(Concept, stored.concept_id)
            assert concept.school_id == school_id
            assert concept.name == "Forces"
            assert stored.comprehension_checkpoints[0]["conceptId"] == str(concept.id)
            assert str(concept.id) != provided
        await engine.dispose()

    asyncio.run(scenario())


async def setup():
    url = make_url(URL)
    assert url.host in {"localhost", "127.0.0.1"}
    assert url.database == "nevo_adaptation_tests"
    engine = create_async_engine(URL, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    school_id, teacher_id = uuid4(), uuid4()
    async with sessions.begin() as session:
        session.add(
            School(
                id=school_id,
                name="Parse test",
                school_code=uuid4().hex[:8],
                school_url_slug=uuid4().hex,
                auth_method="email_password",
            )
        )
        await session.flush()
        session.add(
            User(
                id=teacher_id,
                school_id=school_id,
                role="teacher",
                first_name="Test",
                status="active",
                auth_method="email_password",
            )
        )
    return engine, sessions, teacher_id, school_id


@pytest.mark.skipif(not URL, reason="Disposable database required")
def test_orphaned_staged_upload_is_closed_but_fresh_and_ready_jobs_are_untouched():
    async def scenario():
        engine, sessions, teacher_id, school_id = await setup()
        old_id, fresh_id, ready_id = uuid4(), uuid4(), uuid4()
        old = datetime.now(UTC) - timedelta(hours=2)
        async with sessions.begin() as session:
            for job_id, created, state in (
                (old_id, old, "processing"),
                (fresh_id, datetime.now(UTC), "processing"),
                (ready_id, old, "ready"),
            ):
                session.add(
                    UploadJob(
                        id=job_id,
                        school_id=school_id,
                        requested_by_id=teacher_id,
                        filename="lesson.pdf",
                        scope="lesson",
                        status=state,
                        stage="finding_sections",
                        created_at=created,
                    )
                )
        repository = SqlAlchemyContentParsingRepository(sessions)
        await repository.fail_stale_runs(older_than=timedelta(minutes=30))
        async with sessions() as session:
            job = await session.get(UploadJob, old_id)
            assert job.status == "failed" and job.completed_at is not None
            assert job.failure_reason and job.incident_id
            assert (await session.get(UploadJob, fresh_id)).status == "processing"
            assert (await session.get(UploadJob, ready_id)).status == "ready"
        await engine.dispose()

    asyncio.run(scenario())
