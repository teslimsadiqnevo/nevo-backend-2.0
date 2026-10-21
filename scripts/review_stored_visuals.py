"""Re-review existing image bytes before restoring student delivery."""

import argparse
import asyncio
import io
import json
from collections import Counter
from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import urlparse

import httpx
from PIL import Image
from sqlalchemy import select

from nevo.ai_gateway.config import AiGatewaySettings
from nevo.ai_gateway.safety import POLICY_VERSION, safety_from_settings
from nevo.core.config import get_settings
from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.session import create_engine, create_session_factory
from nevo.visuals.config import VisualGenerationSettings


async def main(apply=False):
    engine = create_engine(get_settings().database_url)
    sessions = create_session_factory(engine)
    guard = safety_from_settings(AiGatewaySettings(), sessions=sessions)
    storage = VisualGenerationSettings()
    allowed_host = urlparse(str(storage.supabase_url)).hostname
    counts = Counter()
    try:
        async with sessions() as session:
            rows = list(
                (
                    await session.execute(
                        select(LessonSegment, Lesson)
                        .join(Lesson, Lesson.id == LessonSegment.lesson_id)
                        .order_by(Lesson.title, LessonSegment.sequence_order)
                    )
                ).all()
            )
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            for segment, lesson in rows:
                original = dict(segment.visual_variant or {})
                if not original or original.get("safetyPolicyVersion") == POLICY_VERSION:
                    continue
                counts["requires_review"] += 1
                if not apply:
                    continue
                try:
                    url = str(original.get("imageUrl") or "")
                    parsed = urlparse(url)
                    if parsed.scheme != "https" or parsed.hostname != allowed_host:
                        raise ValueError("Image outside configured storage")
                    response = await client.get(url)
                    response.raise_for_status()
                    image = Image.open(io.BytesIO(response.content)).convert("RGB")
                    stream = io.BytesIO()
                    image.save(stream, format="PNG")
                    await guard.check(
                        f"Lesson: {lesson.title}\nSection: {segment.title}\n"
                        f"Teaching content: {segment.body}\nCaption: {original.get('caption', '')}",
                        image=stream.getvalue(),
                        phase="output:stored_lesson_visual",
                        context=SimpleNamespace(
                            school_id=lesson.school_id,
                            student_id=None,
                            requester_user_id=lesson.created_by_user_id,
                        ),
                    )
                    async with sessions.begin() as session:
                        current = await session.get(LessonSegment, segment.id, with_for_update=True)
                        if current.visual_variant != original:
                            counts["changed_during_review"] += 1
                            continue
                        current.visual_variant = {
                            **original,
                            "safetyPolicyVersion": POLICY_VERSION,
                            "safetyReviewedAt": datetime.now(UTC).isoformat(),
                        }
                        counts["cleared"] += 1
                except Exception as error:
                    counts["withheld"] += 1
                    print(
                        json.dumps(
                            {"segmentId": str(segment.id), "errorType": type(error).__name__}
                        )
                    )
        print(json.dumps({"applied": apply, "counts": dict(counts)}))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    asyncio.run(main(parser.parse_args().apply))
