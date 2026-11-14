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
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nevo.ai_gateway.config import AiGatewaySettings
from nevo.ai_gateway.safety import SafetyBlocked
from nevo.ai_gateway.wiring import build_ai_gateway
from nevo.content_parsing.upload_worker import UploadParsingWorker
from nevo.content_parsing.wiring import build_content_parsing_service
from nevo.db.models.product import UploadJob

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("reparse")

#: The only finding this will let past, and only at the source check.
ALLOWED_ALONE = {"privacy_abuse"}
WIDENED_PHASE = "lesson_source"

#: What the job must already say. A file that failed some other way is not
#: this script's business.
EXPECTED = "lesson_source: privacy_abuse"


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
            if EXPECTED not in (job.error_message or ""):
                raise SystemExit(
                    "Refusing: this upload was not held at the source check on a "
                    f"privacy finding alone. It says {(job.error_message or '(nothing)')[:120]!r}."
                )
            if not args.i_have_read_the_file:
                print()
                raise SystemExit(
                    "Refusing: pass --i-have-read-the-file. Somebody has to have "
                    "looked at the material and found no personal data in it, and "
                    "there is no version of that which is automatic."
                )

        gateway = build_ai_gateway(sessions, AiGatewaySettings())
        _narrow_the_source_check(gateway.safety)
        service = build_content_parsing_service(sessions, gateway)
        worker = UploadParsingWorker(sessions, service)

        # Put it back in the queue this process is about to drain. The lease
        # the worker takes is the same one production takes, so a live worker
        # cannot pick up the same job underneath this one.
        async with sessions.begin() as session:
            job = await session.get(UploadJob, upload_id, with_for_update=True)
            job.status = "processing"
            job.stage = "receiving_file"
            job.error_message = None
            job.failure_reason = None
            job.parse_lease_token = None
            job.parse_lease_until = None

        print("\nre-parsing...")
        claimed = await worker.process_next()
        if not claimed:
            raise SystemExit(
                "The worker claimed nothing - another worker may have taken it. "
                "Check the job's status before running this again."
            )

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
