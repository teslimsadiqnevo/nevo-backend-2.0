"""Re-parse one upload whose source check refused it on a name alone.

For a teacher's file held at lesson_source with privacy_abuse and nothing
else, where a person has looked at the file and found no personal data in it.
One upload at a time, named on the command line, and it says what it did.

Why this exists rather than a general override. Lydia has already ruled (12
November, policy version 2) that privacy_abuse splits by finding type: serious
where it is exposed credentials or a real person's identifiable details, not
serious where it is an ordinary name, "which is a character in a comprehension
passage nine times out of ten". The implementation of that split is the
baseline and checker work and has not landed. So this applies her existing
ruling to a single file rather than deciding anything new, and it stops being
needed the day the split ships.

What it will not do:

  * It only lets through a finding whose categories are exactly
    {privacy_abuse}. Any other category, alone or alongside, still refuses -
    including a privacy finding that arrives with anything else, because the
    anything else is the part that matters.
  * It only widens lesson_source. Every other phase behaves as it does in
    production.
  * It refuses an upload whose recorded failure was not that, so it cannot be
    pointed at a file that failed for some other reason.

Run it with the live DATABASE_URL set, after reading the file. Reading the file
first is the point: this is a human saying the check was wrong, and there is no
version of that which is automatic.

    python scripts/reparse_upload_held_as_false_positive.py <upload-id>
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nevo.ai_gateway.config import AiGatewaySettings
from nevo.ai_gateway.safety import SafetyBlocked
from nevo.ai_gateway.wiring import build_ai_gateway
from nevo.content_parsing.wiring import build_content_parsing_service
from nevo.db.models.product import UploadJob, UploadSourceBlob

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("reparse")

#: The only finding this will let past, and only at the source check.
ALLOWED_ALONE = {"privacy_abuse"}
WIDENED_PHASE = "lesson_source"


def _narrow_the_source_check(guard) -> None:
    """Let a name-only finding at lesson_source record and pass, this run only.

    Wraps the guard's own check rather than reaching inside it, so everything
    else - the fail-closed behaviour, the recording, the chunking, every other
    phase and every other category - is exactly what production does.
    """

    original = guard.check

    async def check(text, *, phase, context=None, image=None):
        try:
            return await original(text, phase=phase, context=context, image=image)
        except SafetyBlocked as blocked:
            if phase != WIDENED_PHASE or set(blocked.categories or ()) != ALLOWED_ALONE:
                raise
            logger.warning(
                "LETTING A SOURCE FINDING THROUGH phase=%s categories=%s - "
                "a person read this file and found no personal data in it. "
                "Lydia's policy version 2 ruling, applied to one upload.",
                phase,
                ",".join(sorted(blocked.categories or ())),
            )
            return None

    guard.check = check


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upload_id")
    parser.add_argument(
        "--i-have-read-the-file",
        action="store_true",
        help="required: confirms a person looked and found no personal data",
    )
    args = parser.parse_args()
    upload_id = UUID(args.upload_id)

    url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with sessions() as session:
            job = await session.get(UploadJob, upload_id)
            if job is None:
                raise SystemExit(f"No upload {upload_id}")
            print(f"upload   {job.filename}")
            print(f"status   {job.status} / {job.stage}")
            print(f"recorded {(job.error_message or '')[:160]}")
            # Checked against the recorded safety decision rather than the
            # job's error string. The string is overwritten by any later
            # attempt - including a failed run of this script, which is how
            # this guard first refused a file it had itself just touched -
            # while the decision stays on the record.
            held = await session.scalar(
                text(
                    "select count(*) from content_safety_events "
                    "where phase = :phase and action <> 'allow' "
                    "and categories = cast(:cats as jsonb) "
                    "and actor_user_id = :actor "
                    "and created_at between :from_at and :to_at"
                ),
                {
                    "phase": WIDENED_PHASE,
                    "cats": '["privacy_abuse"]',
                    "actor": job.requested_by_id,
                    "from_at": job.created_at - timedelta(minutes=2),
                    "to_at": job.created_at + timedelta(minutes=10),
                },
            )
            print(f"recorded source blocks on a name alone: {held}")
            if not held:
                raise SystemExit(
                    "Refusing: no lesson_source decision on a privacy finding alone "
                    "is recorded for this upload, so it was not held the way this "
                    "script is for."
                )
            if not args.i_have_read_the_file:
                print()
                raise SystemExit(
                    "Refusing: pass --i-have-read-the-file. Somebody has to have "
                    "looked at the material and found no personal data in it, and "
                    "there is no version of that which is automatic."
                )

        gateway = build_ai_gateway(sessions, AiGatewaySettings())
        _narrow_the_source_check(gateway.safety_guard)
        service = build_content_parsing_service(sessions, gateway)

        # Claimed here rather than handed to the queue.
        #
        # The first attempt set the job to processing and called the worker's
        # own process_next. A live worker on Render claimed it first - _claim
        # takes any job marked processing - ran it without this narrowing and
        # blocked it again. So the lease is taken in the same transaction that
        # marks it processing, far enough ahead that no other worker will look
        # at it, and the parse runs here directly.
        from uuid import uuid4

        from nevo.content_parsing.entities import ContentParseRequest
        from nevo.content_parsing.upload_worker import _upload_structure
        from nevo.domain.intelligence.vocabulary import LessonSourceType, UploadStage

        token = uuid4()
        async with sessions.begin() as session:
            job = await session.get(UploadJob, upload_id, with_for_update=True)
            job.status = "processing"
            job.stage = UploadStage.RECEIVING_FILE.value
            job.error_message = None
            job.failure_reason = None
            job.parse_lease_token = token
            job.parse_lease_until = datetime.now(UTC) + timedelta(minutes=40)
            actor_id = job.requested_by_id
            fingerprint = (job.structure or {}).get("sourceCacheKey")

        async with sessions() as session:
            blob = await session.get(UploadSourceBlob, upload_id)
            filename, content = blob.filename, bytes(blob.content)
            metadata = dict(blob.parse_metadata or {})

        from nevo.api.frontend_unblockers import _extract_text, _source_type, _title_from_filename

        read_by_backup = not metadata.get("contentIsExtractedText")
        source_text = (
            _extract_text(filename, content)
            if read_by_backup
            else content.decode("utf-8", errors="replace")
        )
        request = ContentParseRequest(
            title=str(metadata.get("title") or _title_from_filename(filename)),
            source_type=LessonSourceType(metadata.get("sourceType") or _source_type(filename)),
            source_text=source_text,
            source_metadata={
                **({"subject": metadata["subject"]} if metadata.get("subject") else {}),
                **(metadata.get("sourceMetadata") or {}),
                **({"readByBackupReader": True} if read_by_backup else {}),
            },
        )

        print(f"\nre-parsing {len(source_text)} characters...")
        try:
            parsed = await service.parse(
                request=request, requested_by_user_id=actor_id, parse_run_id=upload_id
            )
        except Exception as error:
            async with sessions.begin() as session:
                job = await session.get(UploadJob, upload_id, with_for_update=True)
                job.status = "failed"
                job.error_message = f"{type(error).__name__}: {error}".strip()[:1000]
                job.parse_lease_token = None
                job.parse_lease_until = None
            print(f"\nFAILED AGAIN: {type(error).__name__}: {error}")
            raise SystemExit(1) from error

        async with sessions.begin() as session:
            job = await session.get(UploadJob, upload_id, with_for_update=True)
            job.status = "ready"
            job.stage = UploadStage.READY_TO_ASSIGN.value
            job.structure = {
                **_upload_structure(parsed),
                **({"sourceCacheKey": fingerprint} if fingerprint else {}),
            }
            job.parse_lease_token = None
            job.parse_lease_until = None
            job.completed_at = datetime.now(UTC)

        async with sessions() as session:
            job = await session.get(UploadJob, upload_id)
            print(f"\nstatus   {job.status} / {job.stage}")
            print(f"error    {(job.error_message or '(none)')[:200]}")
            if job.structure:
                notes = [n.get("code") for n in (job.structure.get("reviewNotes") or [])]
                print(f"notes    {notes}")
        sys.exit(0 if job.status != "failed" else 1)
    finally:
        await engine.dispose()


asyncio.run(main())
