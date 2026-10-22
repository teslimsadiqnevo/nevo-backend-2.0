"""Controlled live re-upload of retained original bytes; never modifies the original lesson."""

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

import httpx
from sqlalchemy import select

from nevo.auth.config import AuthSettings
from nevo.auth.wiring import build_auth_service
from nevo.core.config import get_settings
from nevo.db.models.account import User
from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.models.product import UploadJob, UploadSourceBlob
from nevo.db.session import create_engine, create_session_factory
from nevo.ops.media_usage import close_ledger, report


async def main(local=False):
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
            if local:
                from nevo.audio.config import AudioSettings
                from nevo.audio.service import AudioGenerationService
                from nevo.storage.supabase import SupabaseStorage
                from nevo.visuals.config import VisualGenerationSettings

                audio_storage = AudioGenerationService(AudioSettings())._storage
                settings = VisualGenerationSettings()
                image_storage = SupabaseStorage(
                    base_url=str(settings.supabase_url),
                    service_role_key=settings.supabase_service_role_key.get_secret_value(),
                    bucket=settings.storage_bucket,
                    public=settings.storage_public,
                )
                rows = list(
                    await session.scalars(
                        select(LessonSegment).where(LessonSegment.lesson_id == lesson.id)
                    )
                )
                checks = [
                    (medium, str(variant["storagePath"]), storage)
                    for row in rows
                    for medium, variant, storage in (
                        ("audio", row.audio_variant, audio_storage),
                        ("image", row.visual_variant, image_storage),
                    )
                    if variant and variant.get("storagePath")
                ]
                verified = await asyncio.gather(
                    *(storage.exists(path) for _, path, storage in checks)
                )
                if not all(verified):
                    raise RuntimeError(
                        "Referenced media missing in storage; not a valid reuse test"
                    )
                print(json.dumps({"storageObjectsVerified": len(verified)}), flush=True)
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
        transport = None
        if local:
            from fastapi import FastAPI

            from nevo.api.content import get_content_parsing_service
            from nevo.api.product_learning import router

            app = FastAPI()
            app.state.auth_service = auth
            app.state.db_sessions = sessions
            app.dependency_overrides[get_content_parsing_service] = lambda: None
            app.include_router(router)
            transport = httpx.ASGITransport(app=app)
        print(
            json.dumps({"execution": "local-ASGI-real-database" if local else "production-HTTP"}),
            flush=True,
        )
        start = datetime.now(UTC)
        async with httpx.AsyncClient(
            base_url="https://api.nevolearning.com", timeout=90, transport=transport
        ) as client:
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
            print(json.dumps({"response": response.json()}), flush=True)
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
        await close_ledger()
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", action="store_true")
    asyncio.run(main(parser.parse_args().local))
