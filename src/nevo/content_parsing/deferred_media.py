"""Optional media runs after the reviewable lesson commits, never on its critical path."""

import asyncio
import hashlib
import json
import logging
from contextlib import suppress
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select, update

from nevo.ai_gateway.safety import POLICY_VERSION, SafetyBlocked
from nevo.api.lesson_contracts import AudioVariant, VisualVariant, is_practice_question
from nevo.content_parsing.entities import ParsedLessonSegment
from nevo.db.models.content import LessonSegment
from nevo.db.models.deferred_media import DeferredLessonMedia, VisualSafetyRestamp
from nevo.domain.intelligence.vocabulary import ContentModality, LessonContentType
from nevo.visuals.service import VisualEducationalReviewError, VisualGenerationError

logger = logging.getLogger(__name__)


class MediaPreparationFailure(RuntimeError):
    pass


def source_hash(row):
    calculation = row.calculation_variant or {}
    payload = [
        row.body,
        row.title,
        calculation.get("expression"),
        [
            [step.get("stepId"), step.get("prompt"), step.get("answer")]
            for step in calculation.get("steps", [])
        ],
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def core_only(segment):
    calculation = segment.calculation_variant
    if calculation:
        calculation = {
            **calculation,
            "steps": [{**step, "narrationAudio": None} for step in calculation.get("steps", [])],
        }
    pending = (
        bool(segment.audio_variant)
        or ContentModality.VISUAL in segment.available_modalities
        or bool(
            calculation
            and any(
                step.get("narrationAudio")
                for step in (segment.calculation_variant or {}).get("steps", [])
            )
        )
    )
    return replace(
        segment,
        visual_variant=None,
        audio_variant=None,
        calculation_variant=calculation,
        available_modalities=tuple(
            m
            for m in segment.available_modalities
            if m not in {ContentModality.AUDIO, ContentModality.VISUAL}
        ),
        needs_review=segment.needs_review or pending,
        review_reasons=tuple(
            dict.fromkeys(
                [*segment.review_reasons, *(["optional_media_pending_review"] if pending else [])]
            )
        ),
    )


def enqueue_media(session, row, source, actor_id):
    kinds = []
    if (
        ContentModality.VISUAL in source.available_modalities
        and source.content_type != LessonContentType.CALCULATION
        and not is_practice_question(source)
    ):
        kinds.append("image")
    if source.audio_variant or any(
        step.get("narrationAudio") for step in (source.calculation_variant or {}).get("steps", [])
    ):
        kinds.append("audio")
    for kind in kinds:
        session.add(
            DeferredLessonMedia(
                lesson_id=row.lesson_id,
                segment_id=row.id,
                requested_by=actor_id,
                kind=kind,
                status="queued",
                source_hash=source_hash(row),
                payload=asdict(source),
                attempts=0,
            )
        )


def segment_from_payload(payload):
    value = dict(payload)
    value["content_type"] = LessonContentType(value["content_type"])
    value["available_modalities"] = tuple(ContentModality(m) for m in value["available_modalities"])
    for field in ("comprehension_checkpoints", "review_reasons"):
        value[field] = tuple(value.get(field) or [])
    return ParsedLessonSegment(**value)


class DeferredMediaWorker:
    def __init__(self, sessions, parser):
        self.sessions, self.parser = sessions, parser
        self.tasks = []
        self.audio_limit = asyncio.Semaphore(4)

    def start(self):
        if not self.tasks:
            self.tasks = [
                asyncio.create_task(self._run(kind), name=f"lesson-media-{kind}-{i}")
                for kind, count in (("image", 2), ("audio", 4))
                for i in range(count)
            ]
            self.tasks.append(asyncio.create_task(self._run_restamps(), name="lesson-media-restamp"))

    async def stop(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks = []

    async def _run(self, kind):
        while True:
            try:
                if not await self.process_next(kind):
                    await asyncio.sleep(5)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Optional lesson media worker failed")
                await asyncio.sleep(5)

    async def _run_restamps(self):
        while True:
            try:
                if not await self.process_restamp_next():
                    await asyncio.sleep(10)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Stored image safety recheck failed")
                await asyncio.sleep(10)

    async def process_restamp_next(self):
        if not self.parser._visual_generation or not self.parser._visual_generation.recheck_configured:
            return False
        now = datetime.now(UTC)
        async with self.sessions.begin() as session:
            await session.execute(
                update(VisualSafetyRestamp)
                .where(
                    VisualSafetyRestamp.status == "processing",
                    VisualSafetyRestamp.lease_until < now,
                    VisualSafetyRestamp.attempts >= 3,
                )
                .values(status="failed", failure_code="review_unavailable", completed_at=now)
            )
            stamp = LessonSegment.visual_variant["safetyPolicyVersion"].astext
            path = LessonSegment.visual_variant["storagePath"].astext
            caption = LessonSegment.visual_variant["caption"].astext
            record = await session.scalar(
                select(LessonSegment)
                .where(
                    LessonSegment.visual_variant.is_not(None),
                    path.is_not(None),
                    or_(
                        stamp.is_(None), stamp != POLICY_VERSION,
                        caption.is_(None), caption == "Lesson visual",
                        caption == LessonSegment.title,
                    ),
                    ~select(VisualSafetyRestamp.id).where(
                        VisualSafetyRestamp.segment_id == LessonSegment.id,
                        VisualSafetyRestamp.policy_version == POLICY_VERSION,
                        VisualSafetyRestamp.storage_path == path,
                    ).exists(),
                )
                .order_by(LessonSegment.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if record is not None:
                existing = await session.scalar(select(VisualSafetyRestamp).where(
                    VisualSafetyRestamp.segment_id == record.id,
                    VisualSafetyRestamp.policy_version == POLICY_VERSION,
                ).with_for_update())
                if existing is None:
                    session.add(VisualSafetyRestamp(
                        segment_id=record.id, policy_version=POLICY_VERSION,
                        storage_path=record.visual_variant["storagePath"],
                        status="queued", attempts=0,
                    ))
                else:
                    existing.storage_path = record.visual_variant["storagePath"]
                    existing.status, existing.attempts = "queued", 0
                    existing.failure_code = existing.completed_at = existing.lease_until = None
                    existing.caption_candidate = existing.caption_approved_at = existing.caption_approved_by = None
                    existing.caption_approved_by_name = None
                return True
            task = await session.scalar(
                select(VisualSafetyRestamp)
                .where(
                    VisualSafetyRestamp.policy_version == POLICY_VERSION,
                    VisualSafetyRestamp.attempts < 3,
                    or_(
                        VisualSafetyRestamp.status == "queued",
                        (VisualSafetyRestamp.status.in_(["processing", "failed"]))
                        & (VisualSafetyRestamp.lease_until < now),
                    ),
                )
                .order_by(VisualSafetyRestamp.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if task is None:
                return False
            task.status, task.attempts = "processing", task.attempts + 1
            task.lease_until = now + timedelta(minutes=4)
            identity, segment_id, storage_path = task.id, task.segment_id, task.storage_path
            segment = await session.get(LessonSegment, segment_id)
            if segment is None or (segment.visual_variant or {}).get("storagePath") != storage_path:
                task.status, task.completed_at, task.lease_until = "stale", now, None
                return True
            lesson_text = f"{segment.title or ''}\n{segment.body}"
        try:
            async with asyncio.timeout(3 * 60):
                description = await self.parser._visual_generation.recheck_existing(
                    storage_path=storage_path, lesson_text=lesson_text
                )
        except SafetyBlocked:
            await self._complete_restamp(identity, storage_path, failure="content_safety_blocked")
        except VisualEducationalReviewError as error:
            await self._complete_restamp(identity, storage_path, failure=error.category)
        except Exception:
            logger.exception("Stored image review could not complete segment=%s", segment_id)
            await self._complete_restamp(identity, storage_path, failure="review_unavailable")
        else:
            await self._complete_restamp(identity, storage_path, description=description)
        return True

    async def _complete_restamp(self, identity, storage_path, *, failure=None, description=None):
        now = datetime.now(UTC)
        async with self.sessions.begin() as session:
            task = await session.get(VisualSafetyRestamp, identity, with_for_update=True)
            if task is None or task.storage_path != storage_path:
                return
            segment = await session.get(LessonSegment, task.segment_id, with_for_update=True)
            if segment is None or (segment.visual_variant or {}).get("storagePath") != storage_path:
                task.status, task.completed_at, task.lease_until = "stale", now, None
                return
            task.failure_code = failure
            task.caption_candidate = description if not failure else None
            task.completed_at = now
            task.lease_until = None if failure != "review_unavailable" or task.attempts >= 3 else now + timedelta(minutes=5)
            task.status = "failed" if failure == "review_unavailable" else "blocked" if failure else "passed"
            if failure:
                if task.status == "blocked":
                    segment.visual_variant = {
                        key: value for key, value in segment.visual_variant.items()
                        if key != "safetyPolicyVersion"
                    }
                return
            segment.visual_variant = {**segment.visual_variant, "safetyPolicyVersion": POLICY_VERSION}
            job = await session.scalar(select(DeferredLessonMedia).where(
                DeferredLessonMedia.segment_id == segment.id,
                DeferredLessonMedia.kind == "image",
            ).with_for_update())
            if job and (job.result or {}).get("image", {}).get("storagePath") == storage_path:
                job.result = {
                    **job.result,
                    "safetyPolicyVersion": POLICY_VERSION,
                    "image": {**job.result["image"], "safetyPolicyVersion": POLICY_VERSION},
                }

    async def _renew(self, identity, token):
        while True:
            await asyncio.sleep(30)
            async with self.sessions.begin() as session:
                await session.execute(
                    update(DeferredLessonMedia)
                    .where(
                        DeferredLessonMedia.id == identity,
                        DeferredLessonMedia.lease_token == token,
                        DeferredLessonMedia.status == "processing",
                    )
                    .values(lease_until=datetime.now(UTC) + timedelta(minutes=3))
                )

    async def process_next(self, kind):
        now = datetime.now(UTC)
        async with self.sessions.begin() as session:
            await session.execute(
                update(DeferredLessonMedia)
                .where(
                    DeferredLessonMedia.kind == kind,
                    DeferredLessonMedia.status == "processing",
                    DeferredLessonMedia.lease_until < now,
                    DeferredLessonMedia.attempts >= 3,
                )
                .values(
                    status="failed",
                    failure_code="generation_interrupted",
                    completed_at=now,
                    lease_token=None,
                    lease_until=None,
                )
            )
            job = await session.scalar(
                select(DeferredLessonMedia)
                .where(
                    DeferredLessonMedia.kind == kind,
                    DeferredLessonMedia.attempts < 3,
                    or_(
                        DeferredLessonMedia.status == "queued",
                        (DeferredLessonMedia.status == "processing")
                        & (DeferredLessonMedia.lease_until < now),
                    ),
                )
                .order_by(DeferredLessonMedia.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if job is None:
                return False
            token = uuid4()
            job.status, job.lease_token = "processing", token
            job.lease_until, job.attempts = now + timedelta(minutes=3), job.attempts + 1
            identity, payload, actor = job.id, job.payload, job.requested_by
            row = await session.get(LessonSegment, job.segment_id)
            if row is None or source_hash(row) != job.source_hash:
                job.status, job.completed_at = "stale", now
                job.lease_token = job.lease_until = None
                return True
        heartbeat = asyncio.create_task(self._renew(identity, token))
        try:
            async with asyncio.timeout(15 * 60):
                result = await self._generate(kind, segment_from_payload(payload), actor)
            await self._finish(identity, token, result=result)
        except asyncio.CancelledError:
            async with self.sessions.begin() as session:
                await session.execute(
                    update(DeferredLessonMedia)
                    .where(
                        DeferredLessonMedia.id == identity,
                        DeferredLessonMedia.lease_token == token,
                    )
                    .values(status="queued", lease_token=None, lease_until=None)
                )
            raise
        except SafetyBlocked:
            await self._finish(identity, token, failure="content_safety_blocked")
        except VisualEducationalReviewError as error:
            await self._finish(
                identity,
                token,
                failure=(
                    "answer_revealing_content"
                    if error.category == "answer_revealing_content"
                    else "educational_review_failed"
                ),
                result={"reviewReason": error.reason},
            )
        except VisualGenerationError as error:
            failure = (
                "educational_review_failed"
                if "failed educational review" in str(error).casefold()
                else "generation_unavailable"
            )
            await self._finish(identity, token, failure=failure)
        except MediaPreparationFailure as error:
            await self._finish(identity, token, failure=str(error))
        except Exception:
            logger.exception("Optional media generation failed job=%s kind=%s", identity, kind)
            await self._finish(identity, token, failure="generation_unavailable")
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
        return True

    async def _generate(self, kind, source, actor):
        notes = []
        if kind == "image":
            if (
                self.parser._visual_generation is None
                or not self.parser._visual_generation.configured
            ):
                raise MediaPreparationFailure("provider_not_configured")
            generated = await self.parser._generate_segment_visual(
                source, notes, requested_by_user_id=actor
            )
            asset = generated.visual_variant
            if (
                not asset
                or not asset.get("imageUrl")
                or asset.get("safetyPolicyVersion") != POLICY_VERSION
            ):
                if any(
                    "failed educational review" in str(note.get("reason") or "").casefold()
                    for note in notes
                ):
                    raise MediaPreparationFailure("educational_review_failed")
                raise ValueError("Image generation or safety review did not complete")
            image = VisualVariant.model_validate(asset).model_dump(mode="json", by_alias=True)
            return {"image": image, "safetyPolicyVersion": POLICY_VERSION}
        if self.parser._audio_generation is None or not self.parser._audio_generation.configured:
            raise MediaPreparationFailure("provider_not_configured")
        generated = await self.parser._generate_segment_audio(source, self.audio_limit, notes)
        audio = generated.audio_variant
        steps = [
            {"stepId": step["stepId"], "audio": step["narrationAudio"]}
            for step in (generated.calculation_variant or {}).get("steps", [])
            if (step.get("narrationAudio") or {}).get("audioUrl")
        ]
        if not (audio or {}).get("audioUrl") and not steps:
            reasons = " ".join(str(note.get("reason") or "") for note in notes).lower()
            if "quota" in reasons or "status 402" in reasons:
                raise MediaPreparationFailure("provider_quota")
            raise MediaPreparationFailure("generation_unavailable")
        if notes or "calculation_audio_generation_failed" in generated.review_reasons:
            raise ValueError("Narration generation was incomplete")
        scripts = [str((audio or {}).get("script") or "")]
        scripts.extend(str(step["audio"].get("script") or "") for step in steps)
        await self.parser._ai_gateway.check_content(
            "\n".join(scripts), requester_user_id=actor, phase="lesson_narration"
        )
        return {
            "audio": AudioVariant.model_validate(audio).model_dump(mode="json", by_alias=True)
            if audio and audio.get("audioUrl")
            else None,
            "stepNarrations": [
                {
                    "stepId": step["stepId"],
                    "audio": AudioVariant.model_validate(step["audio"]).model_dump(
                        mode="json", by_alias=True
                    ),
                }
                for step in steps
            ],
            "safetyPolicyVersion": POLICY_VERSION,
        }

    async def _finish(self, identity, token, *, result=None, failure=None):
        async with self.sessions.begin() as session:
            job = await session.get(DeferredLessonMedia, identity, with_for_update=True)
            if job is None or job.lease_token != token:
                return
            row = await session.get(LessonSegment, job.segment_id)
            job.completed_at = datetime.now(UTC)
            job.lease_token = job.lease_until = None
            if row is None or source_hash(row) != job.source_hash:
                job.status = "stale"
                return
            job.result, job.failure_code = result, failure
            job.status = "failed" if failure else "awaiting_review"
