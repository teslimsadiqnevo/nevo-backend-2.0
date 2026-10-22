"""Fill source-grounded assessment guidance and retry only missing demo narration."""

import argparse
import asyncio
import json
from uuid import UUID

from sqlalchemy import select

from nevo.ai_gateway.config import AiGatewaySettings
from nevo.ai_gateway.wiring import build_ai_gateway
from nevo.api.lesson_contracts import student_modalities
from nevo.audio.config import AudioSettings
from nevo.audio.service import AudioGenerationError, AudioGenerationService
from nevo.core.config import get_settings
from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.session import create_engine, create_session_factory

LESSON = UUID("3367de9d-be40-4704-8a95-7a197b9824dc")
GUIDANCE = {
    "lesson-assessment-check-1": (
        "Picture a tank",
        [
            "Which particles can pass through this membrane?",
            "Which side is more dilute: pure water or sugar solution?",
        ],
    ),
    "lesson-assessment-check-2": (
        "What happens to a plant cell",
        [
            "Which is more concentrated: the salty soil or the cell sap?",
            "What happens to the cell contents when water moves out?",
        ],
    ),
    "lesson-assessment-check-3": (
        "Why does a hospital drip",
        [
            "What can pure water do to a blood cell that has no cell wall?",
            "How does matching the solution's concentration to blood change water movement?",
        ],
    ),
    "lesson-assessment-check-4": (
        "How does salting fish",
        [
            "Which cells on the fish need water to grow?",
            "What does a very salty surrounding solution do to the water inside those cells?",
        ],
    ),
}


async def main(apply_guidance=False, audio=False):
    engine = create_engine(get_settings().database_url)
    sessions = create_session_factory(engine)
    report = {"guidanceAdded": 0, "audio": {}}
    try:
        async with sessions() as session:
            lesson = await session.get(Lesson, LESSON)
            original = lesson.assessment
            revised = []
            for question in original:
                updated = dict(question)
                if not question.get("guidedQuestions"):
                    prefix, prompts = GUIDANCE[question["id"]]
                    if not question["prompt"].startswith(prefix):
                        raise ValueError("Question changed; refusing to overwrite guidance")
                    updated["guidedQuestions"] = prompts
                    report["guidanceAdded"] += 1
                revised.append(updated)
            rows = list(
                await session.scalars(
                    select(LessonSegment)
                    .where(
                        LessonSegment.lesson_id == LESSON,
                        LessonSegment.sequence_order.in_([1, 3, 4, 5]),
                    )
                    .order_by(LessonSegment.sequence_order)
                )
            )
        if apply_guidance and revised != original:
            gateway = build_ai_gateway(sessions, AiGatewaySettings())
            await gateway.check_content(
                "\n".join(p for q in revised for p in q.get("guidedQuestions", [])),
                requester_user_id=lesson.created_by_user_id,
                phase="output:assessment_guidance",
            )
            async with sessions.begin() as session:
                current = await session.get(Lesson, LESSON, with_for_update=True)
                if current.assessment != original:
                    raise ValueError("Assessment changed during review")
                current.assessment = revised
        generator = AudioGenerationService(AudioSettings()) if audio else None
        for row in rows:
            if (row.audio_variant or {}).get("audioUrl"):
                report["audio"][row.sequence_order] = "already_available"
                continue
            if generator is None:
                report["audio"][row.sequence_order] = "ready_to_retry"
                continue
            script = str((row.audio_variant or {}).get("script") or row.body)
            try:
                generated = await generator.generate(script)
            except AudioGenerationError as error:
                report["audio"][row.sequence_order] = str(error)
                # One account rejection is sufficient; do not spend the quota again per section.
                break
            async with sessions.begin() as session:
                current = await session.get(LessonSegment, row.id, with_for_update=True)
                if current.body != row.body or current.audio_variant != row.audio_variant:
                    raise ValueError("Audio source changed during generation")
                current.audio_variant = generated
                current.available_modalities = list(
                    dict.fromkeys([*(current.available_modalities or []), "audio"])
                )
                current.review_reasons = [
                    reason
                    for reason in (current.review_reasons or [])
                    if reason != "audio_generation_failed"
                ]
                if len(student_modalities(current)) >= 2:
                    current.review_reasons = [
                        reason
                        for reason in current.review_reasons
                        if reason != "fewer_than_two_modalities"
                    ]
                current.needs_review = bool(current.review_reasons)
            report["audio"][row.sequence_order] = "generated_and_stored"
        print(json.dumps(report, sort_keys=True))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply-guidance", action="store_true")
    parser.add_argument("--audio", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.apply_guidance, args.audio))
