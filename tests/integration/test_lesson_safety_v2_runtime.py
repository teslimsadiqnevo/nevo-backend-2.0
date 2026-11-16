"""V2 finding storage and expiry against an explicitly disposable local database."""

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nevo.ai_gateway.safety import (
    ContentSafetyGuard,
    LessonSafetyContext,
    SafetyUnavailable,
)
from nevo.db.models.safety import ContentSafetyEvent
from nevo.ops.scheduled_jobs import expire_safety_review_text_rows

URL = os.getenv("NEVO_RUNTIME_TEST_DATABASE_URL", "")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not URL, reason="Disposable database required"),
]


def local_sessions():
    parsed = make_url(URL)
    assert parsed.host in {"127.0.0.1", "localhost"}
    assert parsed.database == "nevo_adaptation_tests"
    engine = create_async_engine(URL, poolclass=NullPool)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def lesson_context() -> LessonSafetyContext:
    return LessonSafetyContext(
        subject="Biology",
        level="SS1",
        curriculum="Nigerian curriculum",
        source_type="pdf",
        uploader_provenance="authenticated_account",
        review_status="not_reviewed",
        section_id="source-chunk-1",
    )


@pytest.mark.asyncio
async def test_generated_finding_is_captured_then_expired_without_losing_decision():
    engine, sessions = local_sessions()
    material = f"A fictional learner named Ada explains food chains. {uuid4()}"
    digest = hashlib.sha256(material.encode()).hexdigest()
    seen_payloads = []

    def respond(request):
        seen_payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "stop_reason": "tool_use",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "content_safety_decision",
                        "input": {
                            "findings": [
                                {
                                    "category": "privacy_abuse",
                                    "finding_type": "ordinary_name",
                                    "confidence": "high",
                                }
                            ]
                        },
                    }
                ],
            },
        )

    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            guard = ContentSafetyGuard(
                api_key="test-only", client=client, sessions=sessions, policy_v2=True
            )
            await guard.check(
                material,
                phase="output:content_parse.default",
                lesson_context=lesson_context(),
            )
        async with sessions() as session:
            row = await session.scalar(
                select(ContentSafetyEvent).where(ContentSafetyEvent.input_hash == digest)
            )
            assert row is not None
            event_id = row.id
            assert row.action == "record"
            assert row.review_material == material
            assert row.material_expires_at > datetime.now(UTC) + timedelta(days=29)
            assert row.findings[0]["finding_type"] == "ordinary_name"
            assert row.lesson_context["section_id"] == "source-chunk-1"
            assert row.chunk_index == row.chunk_count == 1
            assert row.prompt_hash
        submitted = json.loads(seen_payloads[0]["messages"][0]["content"][0]["text"])
        assert submitted["lessonContext"]["subject"] == "Biology"
        assert await expire_safety_review_text_rows(
            sessions, now=datetime.now(UTC) + timedelta(days=31)
        ) == 1
        async with sessions() as session:
            row = await session.get(ContentSafetyEvent, event_id)
            assert row is not None
            assert row.review_material is None
            assert row.action == "record"
    finally:
        async with sessions.begin() as session:
            await session.execute(
                delete(ContentSafetyEvent).where(ContentSafetyEvent.input_hash == digest)
            )
        await engine.dispose()


@pytest.mark.asyncio
async def test_checker_outage_has_no_safety_event():
    engine, sessions = local_sessions()
    material = f"Synthetic lesson outage probe {uuid4()}"
    digest = hashlib.sha256(material.encode()).hexdigest()
    try:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(503))
        ) as client:
            guard = ContentSafetyGuard(
                api_key="test-only", client=client, sessions=sessions, policy_v2=True
            )
            with pytest.raises(SafetyUnavailable):
                await guard.check(
                    material, phase="lesson_source", lesson_context=lesson_context()
                )
        async with sessions() as session:
            assert await session.scalar(
                select(ContentSafetyEvent.id).where(ContentSafetyEvent.input_hash == digest)
            ) is None
    finally:
        await engine.dispose()
