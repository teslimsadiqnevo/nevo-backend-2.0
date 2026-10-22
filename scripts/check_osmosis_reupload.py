"""Controlled live re-upload of retained original bytes; never modifies the original lesson."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

import httpx

from nevo.auth.config import AuthSettings
from nevo.auth.wiring import build_auth_service
from nevo.core.config import get_settings
from nevo.db.models.account import User
from nevo.db.models.content import Lesson
from nevo.db.models.product import UploadJob, UploadSourceBlob
from nevo.db.session import create_engine, create_session_factory
from nevo.ops.media_usage import report


async def main():
    engine = create_engine(get_settings().database_url)
    sessions = create_session_factory(engine)
    auth = build_auth_service(sessions, AuthSettings())
    token = None
    try:
        async with sessions() as session:
            job = await session.get(UploadJob, UUID("f797428f-2674-4584-81f6-919b28110e5d"))
            blob = await session.get(UploadSourceBlob, job.id)
            actor = await session.get(User, job.requested_by_id)
            if actor.school_id != job.school_id or actor.role.value != "teacher":
                raise RuntimeError("Expected test teacher not found")
            lesson_id = job.structure.get("lessonId")
            lesson = await session.get(Lesson, UUID(str(lesson_id))) if lesson_id else None
            print(
                json.dumps(
                    {
                        "sourceUpload": str(job.id),
                        "sourceLesson": str(lesson_id),
                        "filename": blob.filename,
                        "bytes": len(blob.content),
                        "sha256": hashlib.sha256(blob.content).hexdigest(),
                    }
                ),
                flush=True,
            )
        issued = await auth.issue_for_provisioned_user(actor.id)
        token = issued.access_token
        start = datetime.now(UTC)
        async with httpx.AsyncClient(base_url="https://api.nevolearning.com", timeout=90) as client:
            response = await client.post(
                "/api/v1/uploads",
                headers={"Authorization": f"Bearer {token}"},
                files={"file": (blob.filename, blob.content, blob.content_type)},
                data={
                    "scope": job.scope,
                    **({"subject": lesson.subject} if lesson and lesson.subject else {}),
                },
            )
            response.raise_for_status()
            upload_id = response.json()["uploadId"]
            print(json.dumps({"uploadId": upload_id, "from": start.isoformat()}), flush=True)
            previous = None
            for _ in range(90):
                await asyncio.sleep(15)
                async with sessions() as session:
                    current = await session.get(UploadJob, UUID(upload_id))
                    state = (current.status, current.stage)
                    if state != previous:
                        print(json.dumps({"status": state[0], "stage": state[1]}), flush=True)
                        previous = state
                    if current.status in {"ready", "failed"}:
                        print(
                            json.dumps(
                                {
                                    "lessonId": current.structure.get("lessonId"),
                                    "failure": current.failure_reason,
                                }
                            ),
                            flush=True,
                        )
                        break
            else:
                raise RuntimeError("Upload still processing after observation window")
        end = datetime.now(UTC)
        print(json.dumps(await report(engine, start, end), default=str), flush=True)
    finally:
        if token:
            await auth.logout(token)
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
