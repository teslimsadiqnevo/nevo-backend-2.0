"""Repair authored Osmosis display fields and Amina's existing completion record."""

import argparse
import asyncio
import json
from uuid import UUID

from sqlalchemy import select

from nevo.api.lesson_contracts import InteractiveActivityVariant
from nevo.content_parsing.activity import activity_for_delivery
from nevo.content_parsing.chunks import numbered_paragraphs
from nevo.core.config import get_settings
from nevo.db.models.account import School, User
from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.models.product import LessonProgress
from nevo.db.models.signal_event import LessonSession
from nevo.db.session import create_engine, create_session_factory
from nevo.domain.signal_events.vocabulary import LessonCompletionStatus

LESSON = UUID("3367de9d-be40-4704-8a95-7a197b9824dc")


async def main(apply=False):
    engine = create_engine(get_settings().database_url)
    try:
        async with create_session_factory(engine).begin() as session:
            student = await session.scalar(
                select(User).where(User.login_identifier == "NV-SS1SCI01")
            )
            school = await session.get(School, student.school_id)
            lesson = await session.get(Lesson, LESSON)
            if not school.name.startswith("E2E Test Academy") or lesson.school_id != school.id:
                raise RuntimeError("Expected synthetic test tenant not found")
            progress = await session.scalar(
                select(LessonProgress)
                .where(
                    LessonProgress.student_id == student.id,
                    LessonProgress.lesson_id == LESSON,
                )
                .with_for_update()
            )
            report = {"apply": apply}
            if progress and progress.completed_at and progress.session_id:
                sitting = await session.get(
                    LessonSession, progress.session_id, with_for_update=True
                )
                if (
                    sitting is None
                    or sitting.student_id != student.id
                    or sitting.lesson_id != LESSON
                ):
                    raise RuntimeError("Completion is not linked to the expected sitting")
                report["reviewSession"] = str(sitting.id)
                report["completionRestoredFrom"] = "lesson_progress.completed_at"
                if apply:
                    sitting.completion_status = LessonCompletionStatus.COMPLETED
                    sitting.ended_at = max(progress.completed_at, sitting.started_at)
                    sitting.exit_position = str(progress.segment_position)
            rows = await session.scalars(
                select(LessonSegment)
                .where(
                    LessonSegment.lesson_id == LESSON,
                    LessonSegment.sequence_order.in_([4, 5]),
                )
                .with_for_update()
            )
            for row in rows:
                if row.sequence_order == 4:
                    activity = activity_for_delivery(row.interactive_variant, row.body)
                    checked = InteractiveActivityVariant.model_validate(activity)
                    if len(checked.steps) != 6 or not checked.safety:
                        raise RuntimeError("Expected six authored activity steps and safety line")
                    report["activity"] = {
                        "steps": len(checked.steps),
                        "safetyPresent": True,
                        "outcome": checked.outcome,
                    }
                    if apply:
                        row.interactive_variant = activity
                if row.sequence_order == 5:
                    variants = dict(row.depth_variants or {})
                    simplified = dict(variants.get("simplified") or {})
                    old = str(simplified.get("body") or "")
                    revised = numbered_paragraphs(old)
                    if " ".join(old.split()) != " ".join(revised.split()):
                        raise RuntimeError("Formatting repair changed content")
                    report["practiceQuestionParagraphs"] = len(revised.split("\n\n"))
                    if apply:
                        simplified["body"] = revised
                        variants["simplified"] = simplified
                        row.depth_variants = variants
            print(json.dumps(report), flush=True)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    asyncio.run(main(parser.parse_args().apply))
