"""Database-backed upload parsing worker; jobs survive web-process restarts."""

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import or_, select

from nevo.content_parsing.entities import ContentParseRequest
from nevo.content_parsing.failures import failure_reason, new_incident
from nevo.db.models.product import UploadJob, UploadSourceBlob
from nevo.domain.intelligence.vocabulary import LessonSourceType, UploadStage

logger = logging.getLogger(__name__)
LEASE = timedelta(minutes=2)


class UploadParsingWorker:
    def __init__(self, sessions, parser):
        self.sessions, self.parser = sessions, parser
        self.tasks: list[asyncio.Task] = []

    def start(self):
        if not self.tasks:
            self.tasks = [
                asyncio.create_task(self._run(), name=f"upload-parser-{index}")
                for index in range(2)
            ]

    async def stop(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()

    async def _run(self):
        while True:
            try:
                if not await self.process_next():
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Upload parsing worker loop failed")
                await asyncio.sleep(2)

    async def _claim(self):
        now = datetime.now(UTC)
        async with self.sessions.begin() as session:
            job = await session.scalar(
                select(UploadJob)
                .where(
                    UploadJob.status == "processing",
                    or_(UploadJob.parse_lease_until.is_(None), UploadJob.parse_lease_until <= now),
                )
                .order_by(UploadJob.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if job is None:
                return None
            blob = await session.get(UploadSourceBlob, job.id)
            if blob is None:
                # Old interrupted text uploads did not retain a recoverable source.
                logger.error(
                    "Upload parse cannot resume upload=%s: retained source missing", job.id
                )
                job.status = "failed"
                job.failure_reason = "Preparation was interrupted. Please upload the file again."
                job.error_message = "Upload source was not retained for recovery."
                job.incident_id = new_incident()
                job.completed_at = now
                return None
            token = uuid4()
            job.parse_lease_token = token
            job.parse_lease_until = now + LEASE
            job.parse_attempts += 1
            logger.info(
                "Upload parse claimed upload=%s attempt=%s",
                job.id,
                job.parse_attempts,
            )
            return (
                job.id,
                token,
                blob.filename,
                blob.content,
                dict(blob.parse_metadata or {}),
                job.requested_by_id,
            )

    async def _renew(self, upload_id: UUID, token: UUID):
        while True:
            await asyncio.sleep(30)
            async with self.sessions.begin() as session:
                job = await session.get(UploadJob, upload_id)
                if job is None or job.parse_lease_token != token:
                    return
                job.parse_lease_until = datetime.now(UTC) + LEASE

    async def process_next(self):
        claimed = await self._claim()
        if claimed is None:
            return False
        upload_id, token, filename, content, metadata, actor_id = claimed
        heartbeat = asyncio.create_task(self._renew(upload_id, token))
        try:
            from nevo.api.frontend_unblockers import (
                _extract_text,
                _source_type,
                _title_from_filename,
            )

            source_text = (
                content.decode("utf-8", errors="replace")
                if metadata.get("contentIsExtractedText")
                else _extract_text(filename, content)
            )
            source_type = LessonSourceType(metadata.get("sourceType") or _source_type(filename))
            request = ContentParseRequest(
                title=str(metadata.get("title") or _title_from_filename(filename)),
                source_type=source_type,
                source_text=source_text,
                source_metadata={
                    **({"subject": metadata["subject"]} if metadata.get("subject") else {}),
                    **(metadata.get("sourceMetadata") or {}),
                },
            )

            async def note_stage(stage):
                async with self.sessions.begin() as session:
                    job = await session.get(UploadJob, upload_id)
                    if job is not None and job.parse_lease_token == token:
                        job.stage = stage.value
                        logger.info("Upload parse stage upload=%s stage=%s", upload_id, stage.value)

            async with asyncio.timeout(20 * 60):
                parsed = await self.parser.parse(
                    request=request,
                    requested_by_user_id=actor_id,
                    parse_run_id=upload_id,
                    on_stage=note_stage,
                )
            async with self.sessions.begin() as session:
                job = await session.get(UploadJob, upload_id)
                if job is None or job.parse_lease_token != token:
                    return True
                fingerprint = job.structure.get("sourceCacheKey")
                job.status = "ready"
                job.stage = UploadStage.READY_TO_ASSIGN.value
                job.structure = {
                    **_upload_structure(parsed),
                    **({"sourceCacheKey": fingerprint} if fingerprint else {}),
                }
                job.parse_lease_token = None
                job.parse_lease_until = None
                job.completed_at = datetime.now(UTC)
                logger.info("Upload parse completed upload=%s", upload_id)
        except asyncio.CancelledError:
            await self._release(upload_id, token)
            raise
        except Exception as error:
            if isinstance(error, TimeoutError):
                error = TimeoutError("Upload preparation timed out after 20 minutes")
            incident = new_incident()
            logger.exception("Upload parse %s failed, incident %s", upload_id, incident)
            async with self.sessions.begin() as session:
                job = await session.get(UploadJob, upload_id)
                if job is not None and job.parse_lease_token == token:
                    job.status = "failed"
                    job.error_message = str(error)[:1000]
                    job.incident_id = incident
                    job.failure_reason = failure_reason(error)
                    job.parse_lease_token = None
                    job.parse_lease_until = None
                    job.completed_at = datetime.now(UTC)
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await heartbeat
        return True

    async def _release(self, upload_id: UUID, token: UUID):
        async with self.sessions.begin() as session:
            job = await session.get(UploadJob, upload_id)
            if job is not None and job.parse_lease_token == token:
                job.parse_lease_token = None
                job.parse_lease_until = None


def _upload_structure(parsed):
    from nevo.api.product_learning import _upload_structure as serialize

    return serialize(parsed)
