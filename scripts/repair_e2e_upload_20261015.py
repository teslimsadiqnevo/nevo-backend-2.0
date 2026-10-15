"""Repair only the two E2E lesson defects reported on 15 October; dry-run by default."""

import argparse
import asyncio
from dataclasses import replace

from sqlalchemy import String, cast, select

from nevo.api.lesson_contracts import reading_chunks
from nevo.content_parsing.entities import ParsedLessonSegment
from nevo.content_parsing.service import _normalize_segment, _source_activity
from nevo.core.config import get_settings
from nevo.db.models.account import School
from nevo.db.models.content import Lesson, LessonKeyPoint, LessonSegment
from nevo.db.session import create_engine, create_session_factory
from nevo.domain.intelligence.vocabulary import ContentModality


def restore(value):
    # This exact source-name correction was supplied by the teacher report;
    # never reverse pseudonyms by looking up the school roster.
    if isinstance(value, str):
        return value.replace("Learner-408C2D4F1D", "Ada")
    if isinstance(value, dict):
        return {key: restore(item) for key, item in value.items()}
    if isinstance(value, list):
        return [restore(item) for item in value]
    return value


async def repair(apply: bool):
    engine = create_engine(get_settings().database_url)
    try:
        async with create_session_factory(engine)() as session:
            for prefix in ("df63fc69", "319f2cd2"):
                lesson = (
                    await session.scalars(
                        select(Lesson).where(cast(Lesson.id, String).like(prefix + "%"))
                    )
                ).one()
                school = await session.get(School, lesson.school_id)
                if school is None or "e2e" not in school.name.casefold():
                    raise ValueError("Repair is limited to the reported E2E school")
                segments = list(
                    await session.scalars(
                        select(LessonSegment).where(LessonSegment.lesson_id == lesson.id)
                    )
                )
                changed = 0
                for segment in segments:
                    if prefix == "df63fc69":
                        for field in (
                            "title",
                            "body",
                            "text_variant",
                            "visual_variant",
                            "audio_variant",
                            "interactive_variant",
                            "calculation_variant",
                            "depth_variants",
                            "comprehension_checkpoints",
                        ):
                            old = getattr(segment, field)
                            updated = restore(old)
                            if old != updated:
                                setattr(segment, field, updated)
                                changed += 1
                        segment.reading_chunks = reading_chunks(segment.segment_key, segment.body)
                    elif segment.interactive_variant is None or (
                        segment.interactive_variant.get("title") == "Follow the source activity"
                    ):
                        activity = _source_activity(segment.body, title=segment.title)
                        if activity is None:
                            continue
                        original = ParsedLessonSegment(
                            segment_key=segment.segment_key,
                            sequence_order=segment.sequence_order,
                            content_type=segment.content_type,
                            title=segment.title,
                            body=segment.body,
                            available_modalities=tuple(
                                ContentModality(value) for value in segment.available_modalities
                            ),
                            comprehension_checkpoints=tuple(segment.comprehension_checkpoints),
                            text_variant=segment.text_variant,
                            visual_variant=segment.visual_variant,
                            audio_variant=segment.audio_variant,
                            interactive_variant=activity,
                            calculation_variant=segment.calculation_variant,
                            needs_review=True,
                            review_reasons=tuple(segment.review_reasons),
                        )
                        fixed = _normalize_segment(
                            replace(
                                original,
                                available_modalities=(
                                    *original.available_modalities,
                                    ContentModality.INTERACTIVE,
                                ),
                                review_reasons=tuple(
                                    reason
                                    for reason in original.review_reasons
                                    if reason
                                    not in {
                                        "interactive_activity_missing",
                                        "fewer_than_two_modalities",
                                    }
                                ),
                            )
                        )
                        segment.interactive_variant = activity
                        segment.available_modalities = [
                            value.value for value in fixed.available_modalities
                        ]
                        segment.review_reasons = list(fixed.review_reasons)
                        segment.needs_review = True
                        segment.approved = False
                        segment.approved_at = None
                        changed += 1
                if prefix == "df63fc69":
                    for field in ("title", "description", "recap", "assessment"):
                        setattr(lesson, field, restore(getattr(lesson, field)))
                    points = await session.scalars(
                        select(LessonKeyPoint).where(LessonKeyPoint.lesson_id == lesson.id)
                    )
                    for point in points:
                        for field in ("source_text", "extracted_text", "amended_text"):
                            setattr(point, field, restore(getattr(point, field)))
                print(
                    f"{prefix}: {changed} repaired fields/activities "
                    f"({'apply' if apply else 'dry run'})"
                )
            if apply:
                await session.commit()
            else:
                await session.rollback()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(repair(parser.parse_args().apply))
