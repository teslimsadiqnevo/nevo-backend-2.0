"""Backfill generated answer-bearing guidance for one lesson, held for review."""

from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from sqlalchemy import select

from nevo.ai_gateway.config import AiGatewaySettings
from nevo.ai_gateway.entities import AiGenerationRequest
from nevo.ai_gateway.wiring import build_ai_gateway
from nevo.api.lesson_contracts import GuidedCheckStep
from nevo.content_parsing.service import _json_payload
from nevo.core.config import get_settings
from nevo.db.models.ai_gateway import AiGatewayCall
from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.session import create_engine, create_session_factory
from nevo.domain.ai_gateway.vocabulary import AiService


PROMPT_NAME = "content_guided_steps_backfill.default"


def _content_snapshot(segments: list[LessonSegment]) -> str:
    return json.dumps(
        [
            {
                "id": str(segment.id),
                "body": segment.body,
                "checkpoints": segment.comprehension_checkpoints or [],
            }
            for segment in segments
        ],
        sort_keys=True,
        default=str,
    )


async def backfill(lesson_id: UUID, *, apply: bool, confirm_production_write: bool) -> None:
    settings = get_settings()
    database_url = settings.database_url
    if "ibavgeinubvmktxufvvr" in database_url and not confirm_production_write:
        raise SystemExit("Refusing production write without --confirm-production-write")

    engine = create_engine(database_url)
    sessions = create_session_factory(engine)
    gateway = build_ai_gateway(sessions, AiGatewaySettings())
    try:
        async with sessions() as session:
            lesson = await session.get(Lesson, lesson_id)
            if lesson is None:
                raise SystemExit("Lesson not found")
            segments = list(
                await session.scalars(
                    select(LessonSegment)
                    .where(LessonSegment.lesson_id == lesson_id)
                    .order_by(LessonSegment.sequence_order)
                )
            )
            original_snapshot = _content_snapshot(segments)
            questions: list[dict[str, object]] = []
            locations: dict[str, tuple[LessonSegment, int]] = {}
            source_parts = []
            for segment in segments:
                source_parts.append(f"## {segment.title or segment.segment_key}\n{segment.body}")
                for index, question in enumerate(segment.comprehension_checkpoints or []):
                    if question.get("guidedSteps") or not question.get("guidedQuestions"):
                        continue
                    repair_id = f"{segment.segment_key}-check-{index + 1}"
                    locations[repair_id] = segment, index
                    questions.append(
                        {
                            "repairId": repair_id,
                            "id": question.get("id"),
                            "prompt": question.get("prompt"),
                            "conceptName": question.get("conceptName"),
                            "guidedQuestions": question.get("guidedQuestions"),
                            "answerKey": question.get("answerKey"),
                            "explanation": question.get("explanation"),
                        }
                    )
            if not questions:
                raise SystemExit("No eligible guiding questions are missing expected answers")
            requester_id = lesson.created_by_user_id

        result = await gateway.generate(
            AiGenerationRequest(
                requester_user_id=requester_id,
                service=AiService.LESSON_GENERATION,
                prompt_name=PROMPT_NAME,
                variables={
                    "source_text": "\n\n".join(source_parts),
                    "questions": json.dumps(questions, ensure_ascii=True),
                },
                max_output_tokens=8192,
                timeout_seconds=120,
                json_output=True,
            )
        )
        if result.fallback_used:
            raise SystemExit("Refusing fallback output for generated guidance")
        async with sessions() as session:
            audited_call = await session.get(AiGatewayCall, result.call_id)
            if audited_call is None:
                raise SystemExit("AI gateway did not persist the cost audit row")
            estimated_cost_usd = audited_call.estimated_cost_usd
        payload = _json_payload(result.text)
        rows = payload.get("questions")
        if not isinstance(rows, list) or len(rows) != len(locations):
            raise SystemExit("Model response did not return exactly one item per eligible check")
        generated: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            repair_id = row.get("repairId") if isinstance(row, dict) else None
            raw_steps = row.get("guidedSteps") if isinstance(row, dict) else None
            if repair_id not in locations or repair_id in generated or not isinstance(raw_steps, list):
                raise SystemExit("Model response has a missing, duplicate, or unknown check id")
            if len(raw_steps) != 2:
                raise SystemExit(f"Expected two markable steps for {repair_id}")
            seen_ids: set[str] = set()
            steps = []
            for raw_step in raw_steps:
                step = GuidedCheckStep.model_validate(raw_step)
                if step.id in seen_ids:
                    raise SystemExit(f"Duplicate guided-step id for {repair_id}")
                seen_ids.add(step.id)
                steps.append(step.model_dump(by_alias=True, mode="json"))
            generated[repair_id] = steps

        if not apply:
            print(
                json.dumps(
                    {
                        "lessonId": str(lesson_id),
                        "lessonTitle": lesson.title,
                        "checksGenerated": len(generated),
                        "stepsGenerated": sum(map(len, generated.values())),
                        "inputTokens": result.input_tokens,
                        "outputTokens": result.output_tokens,
                        "estimatedCostUsd": str(estimated_cost_usd),
                        "model": result.model,
                        "aiCallId": str(result.call_id),
                        "persistedPendingReview": False,
                    },
                    indent=2,
                )
            )
            return

        async with sessions() as session, session.begin():
            current_lesson = await session.scalar(
                select(Lesson).where(Lesson.id == lesson_id).with_for_update()
            )
            current_segments = list(
                await session.scalars(
                    select(LessonSegment)
                    .where(LessonSegment.lesson_id == lesson_id)
                    .order_by(LessonSegment.sequence_order)
                    .with_for_update()
                )
            )
            if current_lesson is None or _content_snapshot(current_segments) != original_snapshot:
                raise SystemExit("Lesson content changed during generation; nothing was written")
            by_id = {segment.id: segment for segment in current_segments}
            touched: set[UUID] = set()
            for repair_id, steps in generated.items():
                original_segment, index = locations[repair_id]
                segment = by_id[original_segment.id]
                checkpoints = [dict(item) for item in segment.comprehension_checkpoints or []]
                checkpoints[index]["pendingGuidedSteps"] = steps
                checkpoints[index]["guidedStepsReviewStatus"] = "pending_review"
                segment.comprehension_checkpoints = checkpoints
                segment.needs_review = True
                segment.review_reasons = list(
                    dict.fromkeys([*(segment.review_reasons or []), "guided_steps_review_required"])
                )
                touched.add(segment.id)
            await session.flush()
        print(
            json.dumps(
                {
                    "lessonId": str(lesson_id),
                    "lessonTitle": lesson.title,
                    "checksGenerated": len(generated),
                    "stepsGenerated": sum(map(len, generated.values())),
                    "segmentsPendingReview": len(touched),
                    "inputTokens": result.input_tokens,
                    "outputTokens": result.output_tokens,
                    "estimatedCostUsd": str(estimated_cost_usd),
                    "model": result.model,
                    "aiCallId": str(result.call_id),
                    "persistedPendingReview": True,
                },
                indent=2,
            )
        )
    finally:
        await gateway.close()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lesson-id", required=True, type=UUID)
    parser.add_argument("--apply", action="store_true", help="Persist generated steps as pending")
    parser.add_argument("--confirm-production-write", action="store_true")
    args = parser.parse_args()
    asyncio.run(
        backfill(
            args.lesson_id,
            apply=args.apply,
            confirm_production_write=args.confirm_production_write,
        )
    )


if __name__ == "__main__":
    main()
