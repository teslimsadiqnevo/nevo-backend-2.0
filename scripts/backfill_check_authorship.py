"""Restore source-proven check authorship without approving generated answers."""

import argparse
import asyncio

from sqlalchemy import select

from nevo.api.frontend_unblockers import _extract_text
from nevo.content_parsing.service import _source_has_answer
from nevo.core.config import get_settings
from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.models.product import UploadJob, UploadSourceBlob
from nevo.db.session import create_engine, create_session_factory


async def run(apply: bool):
    engine = create_engine(get_settings().database_url)
    changed_checks = changed_assessments = lessons_seen = 0
    try:
        async with create_session_factory(engine)() as session:
            rows = (await session.execute(
                select(UploadJob, UploadSourceBlob)
                .join(UploadSourceBlob, UploadSourceBlob.upload_id == UploadJob.id)
                .where(UploadJob.structure.has_key("lessonId"))
                .order_by(UploadJob.created_at.desc())
            )).all()
            seen = set()
            for job, blob in rows:
                lesson_id = (job.structure or {}).get("lessonId")
                if not lesson_id or lesson_id in seen:
                    continue
                lesson = await session.get(Lesson, lesson_id)
                if lesson is None:
                    continue
                seen.add(lesson_id)
                lessons_seen += 1
                source = (
                    blob.content.decode("utf-8", errors="replace")
                    if (blob.parse_metadata or {}).get("contentIsExtractedText")
                    else _extract_text(blob.filename, blob.content)
                )
                segments = list(await session.scalars(
                    select(LessonSegment).where(LessonSegment.lesson_id == lesson.id)
                ))
                for segment in segments:
                    questions = list(segment.comprehension_checkpoints or [])
                    touched = False
                    for question in questions:
                        if question.get("authoredBy") != "person" and _source_has_answer(source, question):
                            question["authoredBy"] = "person"
                            changed_checks += 1
                            touched = True
                    if touched:
                        segment.comprehension_checkpoints = questions
                assessment = list(lesson.assessment or [])
                touched = False
                for question in assessment:
                    if question.get("authoredBy") != "person" and _source_has_answer(source, question):
                        question["authoredBy"] = "person"
                        changed_assessments += 1
                        touched = True
                if touched:
                    lesson.assessment = assessment
            if apply:
                await session.commit()
    finally:
        await engine.dispose()
    print({"lessonsWithRetainedSource": lessons_seen, "checksRestored": changed_checks,
           "assessmentItemsRestored": changed_assessments, "applied": apply})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.apply))
