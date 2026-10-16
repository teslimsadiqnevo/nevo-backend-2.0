"""Backfill depth variants (simplify/expand) for existing lessons.

Usage:
    # Dry-run for a specific lesson:
    python -m scripts.backfill_depth_rewrites --lesson-id <UUID> --dry-run

    # Backfill a specific lesson:
    python -m scripts.backfill_depth_rewrites --lesson-id <UUID>

    # Backfill all lessons missing depth variants:
    python -m scripts.backfill_depth_rewrites
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import select

from nevo.ai_gateway.config import AiGatewaySettings
from nevo.ai_gateway.wiring import build_ai_gateway
from nevo.api.lesson_contracts import DepthVariants
from nevo.content_parsing.depth import DepthVariantError, DepthVariantService
from nevo.core.config import get_settings
from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.session import create_engine, create_session_factory

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_depth")


async def backfill(
    *,
    lesson_id: UUID | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    ai_settings = AiGatewaySettings()

    ai_gateway = build_ai_gateway(sessions=session_factory, settings=ai_settings)
    depth_service = DepthVariantService(ai_gateway=ai_gateway)

    if not depth_service.configured:
        logger.error(
            "DepthVariantService is NOT configured! "
            "Ensure AI_ANTHROPIC_API_KEY is set in your environment or Render dashboard."
        )
        await engine.dispose()
        return

    async with session_factory() as session:
        # Query lessons
        stmt = select(Lesson).order_by(Lesson.created_at.desc())
        if lesson_id:
            stmt = stmt.where(Lesson.id == lesson_id)
        if limit:
            stmt = stmt.limit(limit)

        lessons = list(await session.scalars(stmt))
        logger.info("Found %d lesson(s) to process", len(lessons))

        total_updated = 0
        total_skipped = 0
        total_rejected = 0
        total_failed = 0

        for l_idx, lesson in enumerate(lessons, start=1):
            segments_stmt = (
                select(LessonSegment)
                .where(LessonSegment.lesson_id == lesson.id)
                .order_by(LessonSegment.sequence_order)
            )
            segments = list(await session.scalars(segments_stmt))
            logger.info(
                "[%d/%d] Lesson %s ('%s') has %d segments",
                l_idx,
                len(lessons),
                lesson.id,
                lesson.title,
                len(segments),
            )

            lesson_updated = 0
            for segment in segments:
                # Check if depth variants already exist with valid body
                dv = segment.depth_variants or {}
                if isinstance(dv, dict) and (
                    dv.get("simplified", {}).get("body") or dv.get("expanded", {}).get("body")
                ):
                    continue

                if not depth_service.worth_rewriting(segment.body):
                    total_skipped += 1
                    continue

                try:
                    variants, model = await depth_service.generate(
                        title=segment.title,
                        body=segment.body,
                        requested_by_user_id=lesson.created_by_user_id,
                    )
                except DepthVariantError as error:
                    logger.warning(
                        "Segment %s depth rewrite failed: %s", segment.segment_key, error
                    )
                    total_failed += 1
                    continue

                if variants.empty:
                    logger.warning(
                        "Segment %s depth rewrites rejected by checks", segment.segment_key
                    )
                    total_rejected += 1
                    continue

                payload = variants.payload(model=model)
                validated = (
                    TypeAdapter(DepthVariants)
                    .validate_python(payload)
                    .model_dump(by_alias=True, mode="json")
                )

                if not dry_run:
                    segment.depth_variants = validated
                    lesson_updated += 1
                    total_updated += 1
                else:
                    logger.info(
                        "[DRY RUN] Would set depth_variants on %s: simplified=%s, expanded=%s",
                        segment.segment_key,
                        "simplified" in validated,
                        "expanded" in validated,
                    )
                    lesson_updated += 1
                    total_updated += 1

            if not dry_run and lesson_updated > 0:
                await session.commit()
                logger.info(
                    "Committed %d updated segments for lesson %s", lesson_updated, lesson.id
                )

        logger.info(
            "Backfill finished: updated=%d, skipped_short=%d, rejected=%d, failed=%d (dry_run=%s)",
            total_updated,
            total_skipped,
            total_rejected,
            total_failed,
            dry_run,
        )

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill depth variants on lesson segments")
    parser.add_argument(
        "--lesson-id", type=UUID, default=None, help="Specific lesson ID to backfill"
    )
    parser.add_argument("--dry-run", action="store_true", help="Inspect without committing changes")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of lessons")
    args = parser.parse_args()

    asyncio.run(
        backfill(
            lesson_id=args.lesson_id,
            dry_run=args.dry_run,
            limit=args.limit,
        )
    )


if __name__ == "__main__":
    main()
