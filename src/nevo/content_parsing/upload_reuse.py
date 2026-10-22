"""Same-owner unchanged uploads reuse their existing prepared lesson, not new AI prose."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.models.media_usage import media_usage_events
from nevo.db.models.product import UploadJob, UploadSourceBlob
from nevo.domain.intelligence.vocabulary import ContentParseStatus


def source_key(*, text: str, title: str, subject: str | None, source_type: str, scope: str) -> str:
    payload = json.dumps([1, text, title, subject or "", source_type, scope], ensure_ascii=True)
    return hashlib.sha256(payload.encode()).hexdigest()


async def find_reusable_upload(
    session: AsyncSession,
    *,
    actor_id: UUID,
    school_id: UUID,
    scope: str,
    key: str | None = None,
    content: bytes | None = None,
    subject: str | None = None,
) -> UploadJob | None:
    query = select(UploadJob).where(
        UploadJob.requested_by_id == actor_id,
        UploadJob.school_id == school_id,
        UploadJob.scope == scope,
        UploadJob.status == "ready",
    )
    if content is not None:
        query = query.join(UploadSourceBlob).where(UploadSourceBlob.content == content)
    else:
        query = query.where(UploadJob.structure["sourceCacheKey"].astext == key)
    jobs = await session.scalars(query.order_by(UploadJob.created_at.desc()))
    for job in jobs:
        try:
            lesson_id = UUID(str(job.structure.get("lessonId")))
        except ValueError:
            continue
        lesson = await session.get(Lesson, lesson_id)
        if (
            lesson is not None
            and lesson.school_id == school_id
            and (subject is None or lesson.subject == subject)
            and lesson.status
            in {
                ContentParseStatus.COMPLETED,
                ContentParseStatus.COMPLETED_WITH_REVIEW,
            }
        ):
            return job
    return None


async def record_reused_media(session: AsyncSession, job: UploadJob) -> None:
    """Record reused asset references; no provider call, draw, synthesis or asset write."""
    rows = await session.scalars(
        select(LessonSegment).where(LessonSegment.lesson_id == UUID(str(job.structure["lessonId"])))
    )
    paths: set[tuple[str, str]] = set()
    for row in rows:
        variants = [("audio", row.audio_variant), ("image", row.visual_variant)]
        steps = (row.calculation_variant or {}).get("steps", [])
        for step in steps if isinstance(steps, list) else []:
            if isinstance(step, dict):
                variants.append(("audio", step.get("narrationAudio")))
        for medium, variant in variants:
            if isinstance(variant, dict) and variant.get("storagePath"):
                paths.add((medium, str(variant["storagePath"])))
    if paths:
        now = datetime.now(UTC)
        await session.execute(
            media_usage_events.insert(),
            [
                {
                    "id": uuid4(),
                    "run_id": uuid4(),
                    "kind": "generation",
                    "medium": medium,
                    "status": "cache_hit",
                    "asset_path": path,
                    "occurred_at": now,
                    "completed_at": now,
                    "usage": {},
                    "pricing": {},
                }
                for medium, path in sorted(paths)
            ],
        )
        await session.commit()


def reuse_response(job: UploadJob) -> dict[str, object]:
    return {"uploadId": str(job.id), "status": job.status, "stage": job.stage, "reused": True}
