"""Give the seeded school something to learn, on top of seed_clean_slate.

Run after seed_clean_slate.py. Separate because the two answer different
questions: that script proves a school can exist, this one proves a child can
be taught - concepts to be mastered, a lesson made of segments, an assignment
that puts it in front of a child, and the mastery and review rows that make
the progress screens show something other than an empty state.

Reference data that migrations seeded - the canonical subject list, the
subscription tiers, the prompt templates - is not written here. It belongs to
the migrations and is restored from the pre-reset dump, because inventing a
second source for it is how the two drift.

Usage:
    .venv/bin/python scripts/seed_learning.py
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nevo.db.models.account import Class, School, StudentClassEnrollment, User
from nevo.db.models.content import ContentParseRun, Lesson, LessonSegment
from nevo.db.models.frontend_support import Concept, LessonAssignment
from nevo.db.models.mastery import StudentConceptMastery, StudentConceptScheduling
from nevo.domain.accounts.vocabulary import UserRole

#: Concepts per subject, few and real rather than many and invented. A graph
#: this size is enough to show a progress screen with ordinary numbers on it.
CONCEPTS: dict[str, tuple[str, ...]] = {
    "Mathematics": (
        "Fractions",
        "Equivalent fractions",
        "Adding fractions",
        "Decimals",
    ),
    "English Language": ("Nouns", "Verb tense", "Reading comprehension"),
    "Basic Science": ("States of matter", "The water cycle", "Simple circuits"),
    "Basic Technology": ("Hand tools", "Measurement"),
}

LESSON_TITLE = "Adding fractions with the same denominator"

#: Segment bodies kept short. A seed is not a place to write a lesson, and a
#: wall of invented teaching text would be read as content somebody approved.
SEGMENTS: tuple[tuple[str, str, str], ...] = (
    (
        "intro",
        "explanatory_text",
        "When two fractions share a denominator, the bottom number stays as it "
        "is and only the top numbers are added.",
    ),
    (
        "worked",
        "worked_example",
        "One quarter plus two quarters. The denominators match, so add one and "
        "two to get three: three quarters.",
    ),
    (
        "practice",
        "practice_question",
        "Two fifths plus one fifth. Add the top numbers and keep the bottom number the same.",
    ),
)

#: Mastery spread deliberately across the range. A screen where every child
#: sits at the same number tells you nothing about whether it works.
MASTERY_BY_POSITION: tuple[float, ...] = (0.82, 0.64, 0.41, 0.73, 0.55, 0.30)


def database_url() -> str:
    for line in Path(".env").read_text().splitlines():
        match = re.match(r"\s*DATABASE_URL\s*=\s*(.+)", line)
        if match:
            raw = match.group(1).strip().strip('"').strip("'")
            raw = raw.replace("postgresql://", "postgresql+asyncpg://")
            return re.sub(r"[?&]sslmode=\w+", "", raw)
    raise SystemExit("DATABASE_URL not found in .env")


async def seed(session: AsyncSession) -> dict[str, object]:
    now = datetime.now(UTC)
    school = await session.scalar(select(School).limit(1))
    if school is None:
        raise SystemExit("No school. Run seed_clean_slate.py first.")

    teacher = await session.scalar(
        select(User).where(User.school_id == school.id, User.role == UserRole.TEACHER)
    )
    students = list(
        await session.scalars(
            select(User)
            .where(User.school_id == school.id, User.role == UserRole.STUDENT)
            .order_by(User.admission_number)
        )
    )
    assert teacher is not None and students, "seed_clean_slate did not run"

    concepts: dict[str, Concept] = {}
    for subject, names in CONCEPTS.items():
        for name in names:
            concept = Concept(
                school_id=school.id,
                name=name,
                subject=subject,
                source="seed",
            )
            session.add(concept)
            concepts[name] = concept
    await session.flush()

    lesson = Lesson(
        created_by_user_id=teacher.id,
        school_id=school.id,
        title=LESSON_TITLE,
        source_type="text",
        description=(
            "Adding fractions that already share a denominator, before any common-denominator work."
        ),
    )
    session.add(lesson)
    await session.flush()

    parse_run = ContentParseRun(
        lesson_id=lesson.id,
        requested_by_user_id=teacher.id,
        source_type="text",
    )
    session.add(parse_run)
    await session.flush()

    for order, (key, content_type, body) in enumerate(SEGMENTS, start=1):
        session.add(
            LessonSegment(
                lesson_id=lesson.id,
                parse_run_id=parse_run.id,
                segment_key=key,
                content_type=content_type,
                sequence_order=order,
                title=key.replace("_", " ").title(),
                body=body,
                available_modalities=["text"],
            )
        )

    # Assigned to the class that is actually taught this, rather than to
    # everybody: a seed where every child has every lesson hides the join.
    jss1a = await session.scalar(
        select(Class).where(Class.school_id == school.id, Class.name == "JSS 1A")
    )
    enrolled = set(
        await session.scalars(
            select(StudentClassEnrollment.student_id).where(
                StudentClassEnrollment.class_id == (jss1a.id if jss1a else None)
            )
        )
    )
    assigned = 0
    for student in students:
        if student.id in enrolled:
            session.add(
                LessonAssignment(
                    lesson_id=lesson.id,
                    student_id=student.id,
                    teacher_id=teacher.id,
                    assigned_at=now,
                )
            )
            assigned += 1

    # Mastery and review schedules for every child against the maths concepts,
    # so progress, review and the scheduler all have something to read.
    maths = [concepts[name] for name in CONCEPTS["Mathematics"]]
    for position, student in enumerate(students):
        base = MASTERY_BY_POSITION[position % len(MASTERY_BY_POSITION)]
        for offset, concept in enumerate(maths):
            probability = max(0.05, min(0.95, base - offset * 0.07))
            session.add(
                StudentConceptMastery(
                    student_id=student.id,
                    concept_id=concept.id,
                    mastery_probability_concept=probability,
                    mastery_probability_reading=min(0.95, probability + 0.05),
                    last_updated=now,
                )
            )
            session.add(
                StudentConceptScheduling(
                    student_id=student.id,
                    concept_id=concept.id,
                    stability=2.5 + offset,
                    # FSRS difficulty runs 1 to 10, not 0 to 1 - the table
                    # checks it, which is how this seed found out.
                    difficulty=3.0 + offset * 0.5,
                    last_review=now - timedelta(days=offset + 1),
                    # One due today per child, the rest spread forward, so the
                    # review screen is neither empty nor entirely overdue.
                    next_review_due=now + timedelta(days=offset - 1),
                    review_count=offset + 1,
                )
            )
    await session.flush()

    return {
        "lessonId": str(lesson.id),
        "lessonTitle": LESSON_TITLE,
        "segments": len(SEGMENTS),
        "assignedTo": assigned,
        "concepts": sum(len(names) for names in CONCEPTS.values()),
        "masteryRows": len(students) * len(maths),
    }


async def main() -> None:
    engine = create_async_engine(database_url())
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker.begin() as session:
        summary = await seed(session)
    await engine.dispose()
    import json

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
