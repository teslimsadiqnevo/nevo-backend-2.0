"""Sweep stored keys and backend presentation; optionally quarantine unmarkable imports."""

import argparse
import asyncio
import json
from collections import Counter
from uuid import UUID

from sqlalchemy import select

from nevo.api.lesson_contracts import checkpoint_payloads
from nevo.core.config import get_settings
from nevo.db.models.content import ContentParseRun, Lesson, LessonSegment
from nevo.db.models.probe import ProbeItem
from nevo.db.session import create_engine, create_session_factory
from nevo.domain.intelligence.vocabulary import ContentParseStatus
from nevo.probe.presentation import ordered_options

AUDIT_PUPIL = "1a988c48-eec9-4a7e-8332-71772b8a84c6"
OSMOSIS = UUID("3367de9d-be40-4704-8a95-7a197b9824dc")


def inspect(values, *, source, context, totals, issues, demo=None):
    for raw in values:
        totals["items"] += 1
        try:
            row = checkpoint_payloads(
                [raw], segment_key=context, strict=True, presentation_seed=AUDIT_PUPIL
            )[0]
        except (ValueError, TypeError, KeyError) as error:
            totals["invalid"] += 1
            issues.append({"source": source, "context": context, "error": type(error).__name__})
            continue
        if row["answerType"] not in {"single_choice", "multiple_choice"}:
            totals["nonChoice"] += 1
            continue
        totals["choice"] += 1
        if isinstance(row["answerKey"], list):
            totals["multipleAnswer"] += 1
            continue
        position = next(
            i + 1 for i, item in enumerate(row["options"]) if item["value"] == row["answerKey"]
        )
        totals[f"correctAt{position}"] += 1
        original = raw.get("options") or []
        if original:
            first = original[0].get("value") if isinstance(original[0], dict) else original[0]
            totals["storedFirstCorrect"] += first == row["answerKey"]
        if demo is not None:
            demo.append(position)


async def main(quarantine=False):
    engine = create_engine(get_settings().database_url)
    result = {
        "scope": "backend; presentation seed is the synthetic Amina account",
        "quarantinedLessons": [],
        "quickChecks": Counter(),
        "afterLesson": Counter(),
        "onboardingKnowledge": Counter(),
        "issues": [],
        "osmosisQuickPositions": [],
        "osmosisAssessmentPositions": [],
    }
    try:
        async with create_session_factory(engine)() as session:
            lessons = list(await session.scalars(select(Lesson)))
            for lesson in lessons:
                inspect(
                    lesson.assessment or [],
                    source="assessment",
                    context="lesson-assessment",
                    totals=result["afterLesson"],
                    issues=result["issues"],
                    demo=result["osmosisAssessmentPositions"] if lesson.id == OSMOSIS else None,
                )
            for segment in await session.scalars(
                select(LessonSegment).order_by(
                    LessonSegment.lesson_id, LessonSegment.sequence_order
                )
            ):
                previous_issues = len(result["issues"])
                inspect(
                    segment.comprehension_checkpoints or [],
                    source="checkpoint",
                    context=segment.segment_key,
                    totals=result["quickChecks"],
                    issues=result["issues"],
                    demo=result["osmosisQuickPositions"] if segment.lesson_id == OSMOSIS else None,
                )
                if quarantine and len(result["issues"]) > previous_issues:
                    lesson = next(row for row in lessons if row.id == segment.lesson_id)
                    lesson.status = ContentParseStatus.FAILED
                    note = {
                        "code": "unmarkable_question",
                        "message": (
                            "A stored question has no valid answer key. "
                            "Re-upload the source before assigning this lesson."
                        ),
                    }
                    parse_run = await session.get(ContentParseRun, segment.parse_run_id)
                    if parse_run is not None and note not in (parse_run.review_notes or []):
                        parse_run.review_notes = [*(parse_run.review_notes or []), note]
                    segment.needs_review = True
                    segment.approved_at = None
                    segment.approved_by = None
                    segment.review_reasons = sorted(
                        set(segment.review_reasons or []) | {"unmarkable_question"}
                    )
                    result["quarantinedLessons"].append(str(lesson.id))
            for item in await session.scalars(
                select(ProbeItem).where(ProbeItem.retired.is_(False))
            ):
                result["onboardingKnowledge"]["items"] += 1
                options = ordered_options(item.options, seed=f"{AUDIT_PUPIL}:{item.id}")
                position = next(
                    (
                        i + 1
                        for i, option in enumerate(options)
                        if str(option.get("value")) == item.correct_option
                    ),
                    None,
                )
                result["onboardingKnowledge"][f"correctAt{position}"] += 1
                if position is None:
                    result["issues"].append(
                        {"source": "probe", "context": str(item.id), "error": "unmatched_key"}
                    )
            if quarantine:
                await session.commit()
        print(json.dumps(result, indent=2))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quarantine",
        action="store_true",
        help="Block unmarkable legacy imports from student use; preserve source and history.",
    )
    asyncio.run(main(parser.parse_args().quarantine))
