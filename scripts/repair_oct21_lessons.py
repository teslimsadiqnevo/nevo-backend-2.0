"""Idempotent stored-contract repair; does not regenerate teacher-authored content."""

import argparse
import asyncio
import json
from collections import Counter

from sqlalchemy import select

from nevo.api.lesson_contracts import checkpoint_payloads
from nevo.content_parsing.chunks import reading_chunks
from nevo.content_parsing.depth import source_claims
from nevo.core.config import get_settings
from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.models.probe import ProbeItem
from nevo.db.models.product import LessonProgress
from nevo.db.models.signal_event import LessonSession
from nevo.db.session import create_engine, create_session_factory


async def main(apply=False):
    engine = create_engine(get_settings().database_url)
    counts = Counter()
    affected = set()
    try:
        async with create_session_factory(engine).begin() as session:
            for progress in await session.scalars(
                select(LessonProgress).where(
                    LessonProgress.completed_at.is_not(None),
                    LessonProgress.status != "completed",
                )
            ):
                finished = await session.scalar(
                    select(LessonSession)
                    .where(
                        LessonSession.student_id == progress.student_id,
                        LessonSession.lesson_id == progress.lesson_id,
                        LessonSession.completion_status == "completed",
                    )
                    .order_by(LessonSession.ended_at.desc())
                    .limit(1)
                )
                if finished is not None:
                    counts["completed_progress_restored"] += 1
                    if apply:
                        progress.status = "completed"
                        progress.session_id = finished.id
            for lesson in await session.scalars(select(Lesson)):
                normalized = checkpoint_payloads(
                    lesson.assessment or [], segment_key="lesson-assessment"
                )
                if normalized != lesson.assessment:
                    counts["assessment_lessons_normalized"] += 1
                    affected.add(str(lesson.id))
                    if apply:
                        lesson.assessment = normalized
            for row in await session.scalars(select(LessonSegment)):
                normalized = checkpoint_payloads(
                    row.comprehension_checkpoints or [], segment_key=row.segment_key
                )
                if normalized != row.comprehension_checkpoints:
                    counts["checkpoint_sections_normalized"] += 1
                    affected.add(str(row.lesson_id))
                    if apply:
                        row.comprehension_checkpoints = normalized
                chunks = reading_chunks(row.segment_key, row.body)
                if row.reading_chunks != chunks:
                    counts["reading_sections_rechunked"] += 1
                    if apply:
                        # Stable identities for unchanged text; source body is untouched.
                        row.reading_chunks = chunks
                variants = dict(row.depth_variants or {})
                changed = False
                for mode in ("simplified", "expanded"):
                    variant = variants.get(mode)
                    if isinstance(variant, dict) and variant.get("sourceClaims"):
                        claims = source_claims(row.body)
                        if any(
                            str(claim).strip().rstrip(".").isdigit()
                            for claim in variant["sourceClaims"]
                        ):
                            variants[mode] = {**variant, "sourceClaims": claims}
                            changed = True
                if changed and apply:
                    row.depth_variants = variants
            for item in await session.scalars(select(ProbeItem)):
                if item.retired:
                    continue
                from nevo.probe.presentation import standalone_question

                if not standalone_question(item.question):
                    counts["context_dependent_probe_items_retired"] += 1
                    if apply:
                        item.retired = True
            counts["lessons_normalized"] = len(affected)
            if not apply:
                await session.rollback()
        print(json.dumps({"applied": apply, "counts": dict(counts)}, sort_keys=True))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    asyncio.run(main(parser.parse_args().apply))
