from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from nevo.ai_gateway.safety import POLICY_VERSION
from nevo.api.auth import PrincipalDependency
from nevo.api.casing import CAMEL_CONFIG
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_common import require_school_actor
from nevo.content_parsing.deferred_media import source_hash
from nevo.content_parsing.media_contracts import (
    LessonMediaItem,
    LessonMediaResponse,
    MediaCounts,
    MediaPreparation,
)
from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.models.deferred_media import DeferredLessonMedia

router = APIRouter(prefix="/api/v1", tags=["learning product"])


async def media_summary(session, lesson_id):
    counts = {"image": MediaCounts(), "audio": MediaCounts()}
    rows = await session.execute(
        select(
            DeferredLessonMedia.kind,
            DeferredLessonMedia.status,
            func.count(),
        )
        .where(DeferredLessonMedia.lesson_id == lesson_id)
        .group_by(
            DeferredLessonMedia.kind,
            DeferredLessonMedia.status,
        )
    )
    for kind, state, total in rows:
        counts[kind].total += total
        setattr(counts[kind], state, total)
    total = sum(c.total for c in counts.values())
    pending = sum(c.queued + c.processing for c in counts.values())
    awaiting = sum(c.awaiting_review for c in counts.values())
    failed = sum(c.failed + c.stale for c in counts.values())
    phase = (
        "not_requested"
        if not total
        else "preparing"
        if pending
        else "awaiting_review"
        if awaiting
        else "complete_with_errors"
        if failed
        else "complete"
    )
    return MediaPreparation(
        phase=phase, generation_complete=not pending, images=counts["image"], audio=counts["audio"]
    )


async def _lesson(session, principal, lesson_id):
    actor = await require_school_actor(
        session, principal, roles={"teacher", "senco_admin", "other_admin"}
    )
    lesson = await session.get(Lesson, lesson_id)
    if lesson is None or lesson.school_id != actor.school_id:
        raise HTTPException(404, detail="Lesson not found")
    return actor


def _view(job, segment):
    return LessonMediaItem(
        id=job.id,
        segment_id=job.segment_id,
        kind=job.kind,
        status=job.status,
        asset=job.result if job.result and job.status in {"awaiting_review", "approved"} else None,
        source_changed=source_hash(segment) != job.source_hash,
        failure_code=job.failure_code,
        created_at=job.created_at,
        completed_at=job.completed_at,
        approved_at=job.approved_at,
        approved_by=job.approved_by,
        approved_by_name=job.approved_by_name,
    )


@router.get("/lessons/{lesson_id}/media", response_model=LessonMediaResponse)
async def lesson_media(lesson_id: UUID, principal: PrincipalDependency, session: DatabaseSession):
    await _lesson(session, principal, lesson_id)
    rows = await session.execute(
        select(DeferredLessonMedia, LessonSegment)
        .join(
            LessonSegment,
            LessonSegment.id == DeferredLessonMedia.segment_id,
        )
        .where(DeferredLessonMedia.lesson_id == lesson_id)
        .order_by(
            LessonSegment.sequence_order,
            DeferredLessonMedia.kind,
        )
    )
    return LessonMediaResponse(
        lesson_id=lesson_id,
        summary=await media_summary(session, lesson_id),
        items=[_view(job, segment) for job, segment in rows],
    )


async def _job(session, lesson_id, media_id, *, require_current=True):
    job = await session.get(DeferredLessonMedia, media_id, with_for_update=True)
    if job is None or job.lesson_id != lesson_id:
        raise HTTPException(404, detail="Media preparation not found")
    segment = await session.get(LessonSegment, job.segment_id, with_for_update=True)
    if segment is None or (require_current and source_hash(segment) != job.source_hash):
        raise HTTPException(
            409,
            detail={
                "code": "media_source_changed",
                "message": "The section changed. Prepare its media again before approval.",
            },
        )
    return job, segment


async def _approve(session, actor, lesson_id, media_id):
    job, segment = await _job(session, lesson_id, media_id)
    if job.status == "approved":
        return _view(job, segment)
    if job.status != "awaiting_review":
        raise HTTPException(
            409,
            detail={
                "code": "media_not_ready",
                "message": "This media is not ready for review yet.",
            },
        )
    result = job.result or {}
    if result.get("safetyPolicyVersion") != POLICY_VERSION:
        raise HTTPException(409, detail={"code": "media_safety_review_required"})
    if job.kind == "image":
        image = result.get("image") or {}
        if image.get("safetyPolicyVersion") != POLICY_VERSION or not image.get("imageUrl"):
            raise HTTPException(409, detail={"code": "media_safety_review_required"})
        segment.visual_variant = image
    else:
        if result.get("audio"):
            segment.audio_variant = result["audio"]
        if result.get("stepNarrations"):
            calculation = deepcopy(segment.calculation_variant or {})
            narrations = {item["stepId"]: item["audio"] for item in result["stepNarrations"]}
            for step in calculation.get("steps", []):
                if step.get("stepId") in narrations:
                    step["narrationAudio"] = narrations[step["stepId"]]
            segment.calculation_variant = calculation
    modality = "visual" if job.kind == "image" else "audio"
    segment.available_modalities = list(
        dict.fromkeys([*(segment.available_modalities or []), modality])
    )
    job.status, job.approved_at = "approved", datetime.now(UTC)
    job.approved_by = actor.id
    job.approved_by_name = " ".join(filter(None, [actor.first_name, actor.last_name]))
    return _view(job, segment)


@router.post("/lessons/{lesson_id}/media/{media_id}/approve", response_model=LessonMediaItem)
async def approve_media(
    lesson_id: UUID, media_id: UUID, principal: PrincipalDependency, session: DatabaseSession
):
    actor = await _lesson(session, principal, lesson_id)
    result = await _approve(session, actor, lesson_id, media_id)
    await session.commit()
    return result


class MediaApprovalWrite(BaseModel):
    model_config = CAMEL_CONFIG
    media_ids: list[UUID] = Field(min_length=1, max_length=300)


@router.post("/lessons/{lesson_id}/media/approve", response_model=list[LessonMediaItem])
async def approve_media_batch(
    lesson_id: UUID,
    payload: MediaApprovalWrite,
    principal: PrincipalDependency,
    session: DatabaseSession,
):
    actor = await _lesson(session, principal, lesson_id)
    results = [
        await _approve(session, actor, lesson_id, identity)
        for identity in sorted(set(payload.media_ids), key=str)
    ]
    await session.commit()
    return results


@router.post("/lessons/{lesson_id}/media/{media_id}/retry", response_model=LessonMediaItem)
async def retry_media(
    lesson_id: UUID, media_id: UUID, principal: PrincipalDependency, session: DatabaseSession
):
    await _lesson(session, principal, lesson_id)
    job, segment = await _job(session, lesson_id, media_id, require_current=False)
    changed = source_hash(segment) != job.source_hash
    if (
        job.status not in {"failed", "stale"} and not (changed and job.status == "awaiting_review")
    ) or job.approved_at is not None:
        raise HTTPException(409, detail={"code": "media_retry_not_allowed"})
    if source_hash(segment) != job.source_hash:
        payload = dict(job.payload)
        payload.update(body=segment.body, title=segment.title, visual_variant=None)
        payload["audio_variant"] = (
            {"script": segment.body} if payload.get("audio_variant") else None
        )
        calculation = deepcopy(segment.calculation_variant)
        if calculation and job.kind == "audio":
            for step in calculation.get("steps", []):
                step["narrationAudio"] = {"script": step.get("prompt") or ""}
        payload["calculation_variant"] = calculation
        job.payload = payload
        job.source_hash = source_hash(segment)
    job.status, job.attempts = "queued", 0
    job.result = job.failure_code = job.completed_at = job.lease_token = job.lease_until = None
    await session.commit()
    return _view(job, segment)
