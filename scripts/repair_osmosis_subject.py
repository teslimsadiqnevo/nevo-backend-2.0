"""Repair the explicitly reported Biology mapping in the demo lesson."""

import asyncio
import json
from uuid import UUID

from sqlalchemy import or_, select

from nevo.core.config import get_settings
from nevo.db.models.account import Class, StudentClassEnrollment
from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.models.frontend_support import Concept, LessonAssignment
from nevo.db.models.probe import ProbeItem
from nevo.db.models.subject import CanonicalSubject, ClassSubject, SchoolSubject
from nevo.db.session import create_engine, create_session_factory
from nevo.probe.presentation import standalone_question


async def main():
    engine = create_engine(get_settings().database_url)
    try:
        async with create_session_factory(engine).begin() as session:
            lesson = await session.get(
                Lesson, UUID("3367de9d-be40-4704-8a95-7a197b9824dc"), with_for_update=True
            )
            canonical = await session.scalar(
                select(CanonicalSubject).where(CanonicalSubject.slug == "biology")
            )
            if canonical is None:
                raise RuntimeError("Biology absent from canonical curriculum; no subject invented")
            subject = await session.scalar(
                select(SchoolSubject).where(
                    SchoolSubject.school_id == lesson.school_id,
                    SchoolSubject.normalised_name == "biology",
                )
            )
            if subject is None:
                subject = SchoolSubject(
                    school_id=lesson.school_id,
                    name="Biology",
                    normalised_name="biology",
                    origin="canonical",
                    canonical_subject_id=canonical.id,
                    review_state="merged",
                    created_by_user_id=lesson.created_by_user_id,
                )
                session.add(subject)
                await session.flush()
            lesson.subject = "Biology"
            rows = list(
                await session.scalars(
                    select(LessonSegment).where(LessonSegment.lesson_id == lesson.id)
                )
            )
            added = 0
            for row in rows:
                if row.concept_id:
                    concept = await session.get(Concept, row.concept_id)
                    if concept and concept.school_id == lesson.school_id:
                        concept.subject = "Biology"
                for question in row.comprehension_checkpoints or []:
                    answer, options = question.get("answerKey"), question.get("options") or []
                    if (
                        isinstance(answer, list)
                        or answer is None
                        or len(options) < 2
                        or not standalone_question(question.get("prompt", ""))
                    ):
                        continue
                    exists = await session.scalar(
                        select(ProbeItem.id).where(
                            ProbeItem.lesson_id == lesson.id,
                            ProbeItem.question == question["prompt"],
                            ProbeItem.retired.is_(False),
                        )
                    )
                    if exists:
                        continue
                    session.add(
                        ProbeItem(
                            school_id=lesson.school_id,
                            school_subject_id=subject.id,
                            question=question["prompt"],
                            options=options,
                            correct_option=str(answer),
                            lesson_id=lesson.id,
                            concept_id=row.concept_id,
                            band="senior_secondary",
                            difficulty=0.5,
                        )
                    )
                    added += 1
            # Only the reported senior-secondary class, not every class assigned a demonstration.
            classes = list(
                await session.scalars(
                    select(Class)
                    .join(StudentClassEnrollment, StudentClassEnrollment.class_id == Class.id)
                    .join(
                        LessonAssignment,
                        or_(
                            LessonAssignment.class_id == Class.id,
                            LessonAssignment.student_id == StudentClassEnrollment.student_id,
                        ),
                    )
                    .where(
                        LessonAssignment.lesson_id == lesson.id,
                        Class.school_id == lesson.school_id,
                        or_(
                            Class.year_group.in_(["SS1", "SS 1", "SSS1", "SSS 1"]),
                            Class.name == "SS 1 Science",
                        ),
                    )
                    .distinct()
                )
            )
            for school_class in classes:
                if not await session.scalar(
                    select(ClassSubject.id).where(
                        ClassSubject.class_id == school_class.id,
                        ClassSubject.school_subject_id == subject.id,
                    )
                ):
                    session.add(
                        ClassSubject(class_id=school_class.id, school_subject_id=subject.id)
                    )
            print(
                json.dumps(
                    {
                        "subject": "Biology",
                        "probeItemsAdded": added,
                        "seniorClassesLinked": len(classes),
                    }
                )
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
