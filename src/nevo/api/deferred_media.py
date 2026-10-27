from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select, update

from nevo.ai_gateway.safety import POLICY_VERSION
from nevo.api.auth import PrincipalDependency
from nevo.api.casing import CAMEL_CONFIG
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_common import require_school_actor
from nevo.api.response_models import CamelResponse
from nevo.content_parsing.deferred_media import source_hash
from nevo.content_parsing.media_contracts import (
    LessonMediaItem,
    LessonMediaResponse,
    MediaCounts,
    MediaPreparation,
)
from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.models.deferred_media import DeferredLessonMedia, VisualSafetyRestamp

router = APIRouter(prefix="/api/v1", tags=["learning product"])
WITHDRAWAL_UNDO_WINDOW = timedelta(hours=24)
REVIEW_EXCLUDED_FAILURES = frozenset(
    {"content_safety_blocked", "answer_revealing_content"}
)


class MediaQualityEvent(CamelResponse):
    lesson_id: UUID
    lesson_title: str
    segment_id: UUID
    segment_title: str | None
    kind: Literal["image", "audio"]
    category: str
    reason: str
    detected_at: datetime | None
    attempt_count: int


class VisualCaptionReview(CamelResponse):
    segment_id: UUID
    segment_title: str | None
    caption: str
    image_url: str | None
    safety_reviewed_at: datetime | None


class VisualCaptionApproval(CamelResponse):
    approved_count: int
    approved_by: UUID
    approved_by_name: str
    approved_at: datetime


class VisualCaptionEdit(BaseModel):
    caption: str = Field(min_length=12, max_length=240)

    @field_validator("caption")
    @classmethod
    def clean_caption(cls, value):
        text = " ".join(value.split())
        if len(text) < 12:
            raise ValueError("A descriptive caption is required")
        return text


class VisualRestampRetry(CamelResponse):
    queued_count: int


@router.post(
    "/lessons/{lesson_id}/visual-captions/retry-unavailable",
    response_model=VisualRestampRetry,
)
async def retry_unavailable_visual_reviews(
    lesson_id: UUID, principal: PrincipalDependency, session: DatabaseSession,
):
    await _lesson(session, principal, lesson_id)
    result = await session.execute(
        update(VisualSafetyRestamp)
        .where(
            VisualSafetyRestamp.segment_id.in_(
                select(LessonSegment.id).where(LessonSegment.lesson_id == lesson_id)
            ),
            VisualSafetyRestamp.policy_version == POLICY_VERSION,
            VisualSafetyRestamp.status == "failed",
            VisualSafetyRestamp.failure_code == "review_unavailable",
        )
        .values(status="queued", attempts=0, lease_until=None, failure_code=None, completed_at=None)
    )
    await session.commit()
    return VisualRestampRetry(queued_count=result.rowcount or 0)


@router.get("/lessons/{lesson_id}/visual-captions", response_model=list[VisualCaptionReview])
async def pending_visual_captions(
    lesson_id: UUID, principal: PrincipalDependency, session: DatabaseSession,
):
    await _lesson(session, principal, lesson_id)
    rows = (await session.execute(
        select(VisualSafetyRestamp, LessonSegment)
        .join(LessonSegment, LessonSegment.id == VisualSafetyRestamp.segment_id)
        .where(
            LessonSegment.lesson_id == lesson_id,
            VisualSafetyRestamp.policy_version == POLICY_VERSION,
            VisualSafetyRestamp.status == "passed",
            VisualSafetyRestamp.caption_candidate.is_not(None),
            VisualSafetyRestamp.caption_approved_at.is_(None),
        )
        .order_by(LessonSegment.sequence_order)
    )).all()
    return [
        VisualCaptionReview(
            segment_id=segment.id, segment_title=segment.title,
            caption=restamp.caption_candidate,
            image_url=(segment.visual_variant or {}).get("imageUrl"),
            safety_reviewed_at=restamp.completed_at,
        )
        for restamp, segment in rows
        if (segment.visual_variant or {}).get("storagePath") == restamp.storage_path
    ]


@router.post(
    "/lessons/{lesson_id}/visual-captions/approve-all",
    response_model=VisualCaptionApproval,
    responses={409: {"description": "visual_caption_review_changed"}},
)
async def approve_visual_captions(
    lesson_id: UUID,
    segment_ids: list[UUID],
    principal: PrincipalDependency,
    session: DatabaseSession,
):
    actor = await _lesson(session, principal, lesson_id)
    if not segment_ids or len(segment_ids) != len(set(segment_ids)):
        raise HTTPException(422, detail={"code": "invalid_visual_caption_selection"})
    rows = (await session.execute(
        select(VisualSafetyRestamp, LessonSegment)
        .join(LessonSegment, LessonSegment.id == VisualSafetyRestamp.segment_id)
        .where(
            LessonSegment.lesson_id == lesson_id,
            LessonSegment.id.in_(segment_ids),
            VisualSafetyRestamp.policy_version == POLICY_VERSION,
        )
        .with_for_update()
    )).all()
    if len(rows) != len(segment_ids) or any(
        restamp.status != "passed"
        or not restamp.caption_candidate
        or restamp.caption_approved_at is not None
        or (segment.visual_variant or {}).get("storagePath") != restamp.storage_path
        or (segment.visual_variant or {}).get("safetyPolicyVersion") != POLICY_VERSION
        for restamp, segment in rows
    ):
        raise HTTPException(409, detail={"code": "visual_caption_review_changed"})
    now = datetime.now(UTC)
    reviewer_name = " ".join(part for part in (actor.first_name, actor.last_name) if part) or actor.email or str(actor.id)
    for restamp, segment in rows:
        restamp.caption_approved_by = actor.id
        restamp.caption_approved_by_name = reviewer_name
        restamp.caption_approved_at = now
        segment.visual_variant = {
            **segment.visual_variant,
            "caption": restamp.caption_candidate,
            "altText": restamp.caption_candidate,
            "captionAuthoredBy": "nevo",
        }
    await session.commit()
    return VisualCaptionApproval(approved_count=len(rows), approved_by=actor.id, approved_by_name=reviewer_name, approved_at=now)


@router.put(
    "/lessons/{lesson_id}/visual-captions/{segment_id}",
    response_model=VisualCaptionApproval,
    responses={409: {"description": "visual_caption_review_changed"}},
)
async def edit_visual_caption(
    lesson_id: UUID,
    segment_id: UUID,
    payload: VisualCaptionEdit,
    principal: PrincipalDependency,
    session: DatabaseSession,
):
    actor = await _lesson(session, principal, lesson_id)
    segment = await session.get(LessonSegment, segment_id, with_for_update=True)
    restamp = await session.scalar(
        select(VisualSafetyRestamp)
        .where(
            VisualSafetyRestamp.segment_id == segment_id,
            VisualSafetyRestamp.policy_version == POLICY_VERSION,
        )
        .with_for_update()
    )
    if segment is None or segment.lesson_id != lesson_id:
        raise HTTPException(404, detail={"code": "lesson_section_not_found"})
    if (
        restamp is None or restamp.status != "passed"
        or restamp.caption_approved_at is not None
        or (segment.visual_variant or {}).get("storagePath") != restamp.storage_path
        or (segment.visual_variant or {}).get("safetyPolicyVersion") != POLICY_VERSION
    ):
        raise HTTPException(409, detail={"code": "visual_caption_review_changed"})
    now = datetime.now(UTC)
    reviewer_name = " ".join(part for part in (actor.first_name, actor.last_name) if part) or actor.email or str(actor.id)
    segment.visual_variant = {
        **segment.visual_variant,
        "caption": payload.caption,
        "altText": payload.caption,
        "captionAuthoredBy": "person",
    }
    restamp.caption_approved_by, restamp.caption_approved_at = actor.id, now
    restamp.caption_approved_by_name = reviewer_name
    await session.commit()
    return VisualCaptionApproval(approved_count=1, approved_by=actor.id, approved_by_name=reviewer_name, approved_at=now)


def reviewable_media():
    return or_(
        DeferredLessonMedia.failure_code.is_(None),
        DeferredLessonMedia.failure_code.notin_(REVIEW_EXCLUDED_FAILURES),
    )


@router.get(
    "/admin/media-quality-events",
    response_model=list[MediaQualityEvent],
    tags=["school administration"],
)
async def media_quality_events(
    principal: PrincipalDependency,
    session: DatabaseSession,
    limit: int = Query(100, ge=1, le=200),
):
    """Show withheld media and repeat failures to school administrators only."""
    actor = await require_school_actor(
        session, principal, roles={"senco_admin", "other_admin"}
    )
    rows = await session.execute(
        select(DeferredLessonMedia, Lesson, LessonSegment)
        .join(Lesson, Lesson.id == DeferredLessonMedia.lesson_id)
        .join(LessonSegment, LessonSegment.id == DeferredLessonMedia.segment_id)
        .where(
            Lesson.school_id == actor.school_id,
            DeferredLessonMedia.status.in_(["failed", "stale"]),
            DeferredLessonMedia.failure_code.is_not(None),
        )
        .order_by(DeferredLessonMedia.completed_at.desc())
        .limit(limit)
    )
    events = [
        MediaQualityEvent(
            lesson_id=lesson.id,
            lesson_title=lesson.title,
            segment_id=segment.id,
            segment_title=segment.title,
            kind=job.kind,
            category=job.failure_code,
            reason=str((job.result or {}).get("reviewReason") or job.failure_code),
            detected_at=job.completed_at,
            attempt_count=job.attempts,
        )
        for job, lesson, segment in rows
    ]
    restamps = (await session.execute(
        select(VisualSafetyRestamp, Lesson, LessonSegment)
        .join(LessonSegment, LessonSegment.id == VisualSafetyRestamp.segment_id)
        .join(Lesson, Lesson.id == LessonSegment.lesson_id)
        .where(
            Lesson.school_id == actor.school_id,
            VisualSafetyRestamp.policy_version == POLICY_VERSION,
            VisualSafetyRestamp.status.in_(["blocked", "failed"]),
        )
        .order_by(VisualSafetyRestamp.completed_at.desc())
        .limit(limit)
    )).all()
    events.extend(
        MediaQualityEvent(
            lesson_id=lesson.id,
            lesson_title=lesson.title,
            segment_id=segment.id,
            segment_title=segment.title,
            kind="image",
            category=review.failure_code or "review_unavailable",
            reason=review.failure_code or "Stored image review could not complete.",
            detected_at=review.completed_at,
            attempt_count=review.attempts,
        )
        for review, lesson, segment in restamps
    )
    return sorted(events, key=lambda item: item.detected_at or datetime.min.replace(tzinfo=UTC), reverse=True)[:limit]


async def media_summary(session, lesson_id):
    counts = {"image": MediaCounts(), "audio": MediaCounts()}
    rows = await session.execute(
        select(
            DeferredLessonMedia.kind,
            DeferredLessonMedia.status,
            func.count(),
        )
        .where(DeferredLessonMedia.lesson_id == lesson_id, reviewable_media())
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
    lesson = await session.get(Lesson, lesson_id, with_for_update=True)
    if lesson is None or lesson.school_id != actor.school_id:
        raise HTTPException(404, detail="Lesson not found")
    return actor


def _restore_unavailable_reason(job, segment, now):
    if job.status != "withdrawn" or job.withdrawn_at is None:
        return "media_not_withdrawn"
    if job.restored_at is not None:
        return "media_withdrawal_already_restored"
    if now >= job.withdrawn_at + WITHDRAWAL_UNDO_WINDOW:
        return "media_withdrawal_undo_expired"
    if source_hash(segment) != job.source_hash:
        return "media_restore_source_changed"
    result = job.result or {}
    if job.kind == "image":
        image = result.get("image") or {}
        if (
            image.get("safetyPolicyVersion") != POLICY_VERSION
            or not image.get("imageUrl")
        ):
            return "media_restore_review_required"
    else:
        narrations = result.get("stepNarrations") or []
        has_narration = any(
            isinstance(item, dict)
            and isinstance(item.get("stepId"), str)
            and isinstance(item.get("audio"), dict)
            for item in narrations
        )
        if job.approved_at is None or not (
            (result.get("audio") or {}).get("audioUrl") or has_narration
        ):
            return "media_restore_review_required"
    return None


def _view(job, segment):
    now = datetime.now(UTC)
    unavailable_reason = (
        _restore_unavailable_reason(job, segment, now)
        if job.status == "withdrawn"
        else None
    )
    can_undo = unavailable_reason is None and job.status == "withdrawn"
    undo_until = (
        job.withdrawn_at + WITHDRAWAL_UNDO_WINDOW
        if can_undo and job.withdrawn_at
        else None
    )
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
        withdrawn_at=job.withdrawn_at,
        withdrawn_by=job.withdrawn_by,
        withdrawn_by_name=job.withdrawn_by_name,
        withdrawal_reason=job.withdrawal_reason,
        withdrawal_reason_by=job.withdrawal_reason_by,
        withdrawal_reason_at=job.withdrawal_reason_at,
        can_undo=can_undo,
        undo_unavailable_reason=unavailable_reason,
        undo_available_until=undo_until,
        restored_at=job.restored_at,
        restored_by=job.restored_by,
        restored_by_name=job.restored_by_name,
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
        .where(DeferredLessonMedia.lesson_id == lesson_id, reviewable_media())
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


async def _job(
    session,
    lesson_id,
    media_id,
    *,
    require_current=True,
    allow_answer_revealing_retry=False,
):
    job = await session.get(DeferredLessonMedia, media_id, with_for_update=True)
    excluded_failure = job.failure_code in REVIEW_EXCLUDED_FAILURES if job else False
    answer_revealing_retry = (
        allow_answer_revealing_retry and job and job.failure_code == "answer_revealing_content"
    )
    if (
        job is None
        or job.lesson_id != lesson_id
        or (excluded_failure and not answer_revealing_retry)
    ):
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
        if not (result.get("audio") or {}).get("audioUrl") and not result.get("stepNarrations"):
            raise HTTPException(409, detail={"code": "media_not_ready"})
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
    # The next asset can lock/reload this same section; preserve both writes
    # inside the transaction even though request sessions disable autoflush.
    await session.flush()
    return _view(job, segment)


async def _withdraw(job, segment, actor):
    if job.status == "withdrawn":
        return _view(job, segment)
    if job.status != "approved":
        raise HTTPException(409, detail={"code": "media_not_live"})
    if job.kind == "image":
        segment.visual_variant = None
    else:
        segment.audio_variant = None
        calculation = deepcopy(segment.calculation_variant or {})
        for step in calculation.get("steps", []):
            step.pop("narrationAudio", None)
        if calculation:
            segment.calculation_variant = calculation
    modality = "visual" if job.kind == "image" else "audio"
    segment.available_modalities = [
        item for item in (segment.available_modalities or []) if item != modality
    ]
    job.status = "withdrawn"
    job.withdrawn_at = datetime.now(UTC)
    job.withdrawn_by = actor.id
    job.withdrawn_by_name = " ".join(filter(None, [actor.first_name, actor.last_name]))
    job.withdrawal_reason = None
    job.withdrawal_reason_by = None
    job.withdrawal_reason_at = None
    job.restored_at = None
    job.restored_by = None
    job.restored_by_name = None
    return _view(job, segment)


@router.post("/lessons/{lesson_id}/media/{media_id}/withdraw", response_model=LessonMediaItem)
async def withdraw_media(
    lesson_id: UUID, media_id: UUID, principal: PrincipalDependency, session: DatabaseSession
):
    """Withdraw one live asset, without changing a child's sitting or generating media."""
    actor = await _lesson(session, principal, lesson_id)
    job, segment = await _job(session, lesson_id, media_id, require_current=False)
    result = await _withdraw(job, segment, actor)
    await session.commit()
    return result


@router.post("/lessons/{lesson_id}/media/{media_id}/restore", response_model=LessonMediaItem)
async def restore_media(
    lesson_id: UUID, media_id: UUID, principal: PrincipalDependency, session: DatabaseSession
):
    """Undo a withdrawal during the short recovery window, using the stored asset."""
    actor = await _lesson(session, principal, lesson_id)
    job, segment = await _job(session, lesson_id, media_id, require_current=False)
    now = datetime.now(UTC)
    unavailable_reason = _restore_unavailable_reason(job, segment, now)
    if unavailable_reason:
        raise HTTPException(409, detail={"code": unavailable_reason})
    result = job.result or {}
    if job.kind == "image":
        image = result.get("image") or {}
        segment.visual_variant = image
    else:
        audio = result.get("audio") or {}
        narrations = result.get("stepNarrations") or []
        if audio.get("audioUrl"):
            segment.audio_variant = audio
        if narrations:
            calculation = deepcopy(segment.calculation_variant or {})
            by_step = {
                item["stepId"]: item["audio"]
                for item in narrations
                if isinstance(item, dict)
                and isinstance(item.get("stepId"), str)
                and isinstance(item.get("audio"), dict)
            }
            for step in calculation.get("steps", []):
                if step.get("stepId") in by_step:
                    step["narrationAudio"] = by_step[step["stepId"]]
            segment.calculation_variant = calculation
    modality = "visual" if job.kind == "image" else "audio"
    segment.available_modalities = list(
        dict.fromkeys([*(segment.available_modalities or []), modality])
    )
    job.status = "approved"
    job.restored_at = now
    job.restored_by = actor.id
    job.restored_by_name = " ".join(filter(None, [actor.first_name, actor.last_name]))
    await session.commit()
    return _view(job, segment)


class WithdrawalReasonRequest(BaseModel):
    model_config = CAMEL_CONFIG
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Reason cannot be blank")
        return value


@router.patch(
    "/lessons/{lesson_id}/media/{media_id}/withdrawal-reason",
    response_model=LessonMediaItem,
)
async def add_withdrawal_reason(
    lesson_id: UUID,
    media_id: UUID,
    payload: WithdrawalReasonRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
):
    """Attach an optional explanation after the time-sensitive withdrawal."""
    actor = await _lesson(session, principal, lesson_id)
    job, segment = await _job(session, lesson_id, media_id, require_current=False)
    if job.withdrawn_at is None:
        raise HTTPException(409, detail={"code": "media_not_withdrawn"})
    if job.withdrawal_reason is not None:
        raise HTTPException(409, detail={"code": "media_withdrawal_reason_already_recorded"})
    job.withdrawal_reason = payload.reason
    job.withdrawal_reason_by = actor.id
    job.withdrawal_reason_at = datetime.now(UTC)
    await session.commit()
    return _view(job, segment)


@router.post(
    "/lessons/{lesson_id}/segments/{segment_id}/media/{kind}/withdraw",
    response_model=LessonMediaItem,
)
async def withdraw_segment_media(
    lesson_id: UUID,
    segment_id: UUID,
    kind: Literal["image", "audio"],
    principal: PrincipalDependency,
    session: DatabaseSession,
):
    """Also covers live media created before deferred preparation was introduced."""
    actor = await _lesson(session, principal, lesson_id)
    segment = await session.get(LessonSegment, segment_id, with_for_update=True)
    if not segment or segment.lesson_id != lesson_id:
        raise HTTPException(404, detail="Section not found")
    job = await session.scalar(
        select(DeferredLessonMedia)
        .where(DeferredLessonMedia.segment_id == segment_id, DeferredLessonMedia.kind == kind)
        .with_for_update()
    )
    if job is None:
        asset = segment.visual_variant if kind == "image" else segment.audio_variant
        steps = (
            [
                {"stepId": step["stepId"], "audio": step["narrationAudio"]}
                for step in (segment.calculation_variant or {}).get("steps", [])
                if step.get("narrationAudio")
            ]
            if kind == "audio"
            else []
        )
        if not asset and not steps:
            raise HTTPException(404, detail="Live media not found")
        job = DeferredLessonMedia(
            lesson_id=lesson_id,
            segment_id=segment_id,
            requested_by=actor.id,
            kind=kind,
            status="approved",
            source_hash=source_hash(segment),
            payload={},
            result={"image" if kind == "image" else "audio": asset, "stepNarrations": steps},
            approved_at=datetime.now(UTC),
            approved_by=actor.id,
            approved_by_name=" ".join(filter(None, [actor.first_name, actor.last_name])),
        )
        session.add(job)
        await session.flush()
    result = await _withdraw(job, segment, actor)
    await session.commit()
    return result


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
    actor = await _lesson(session, principal, lesson_id)
    job, segment = await _job(
        session,
        lesson_id,
        media_id,
        require_current=False,
        allow_answer_revealing_retry=True,
    )
    if (
        job.status not in {"failed", "stale", "awaiting_review"}
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
    job.requested_by = actor.id
    job.status, job.attempts = "queued", 0
    job.result = job.failure_code = job.completed_at = job.lease_token = job.lease_until = None
    await session.commit()
    return _view(job, segment)
