"""A regenerate must never replace a written lesson with fallback text.

Running a parse against an environment with no model configured produces a
lesson of split-up source text. Storing that silently destroys work that was
good, which is exactly what happened once.
"""
import os
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from nevo.content_parsing.entities import (
    ContentParseRequest,
    ParsedLesson,
    ParsedLessonSegment,
)
from nevo.content_parsing.repositories import SqlAlchemyContentParsingRepository
from nevo.core.config import get_settings
from nevo.db.models.account import School, User
from nevo.db.models.content import LessonSegment
from nevo.db.session import create_engine
from nevo.domain.accounts.vocabulary import AuthMethod, UserRole, UserStatus
from nevo.domain.intelligence.vocabulary import (
    ContentModality,
    LessonContentType,
    LessonSourceType,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL"),
        reason="TEST_DATABASE_URL is required for PostgreSQL integration tests",
    ),
]


def segment(*, key: str, fallback: bool) -> ParsedLessonSegment:
    return ParsedLessonSegment(
        segment_key=key,
        content_type=LessonContentType.EXPLANATORY_TEXT,
        sequence_order=1,
        title="A part",
        body="Some lesson text.",
        available_modalities=(ContentModality.TEXT,),
        review_reasons=("deterministic_parse_used",) if fallback else (),
        needs_review=fallback,
    )


def lesson(*, fallback: bool) -> ParsedLesson:
    return ParsedLesson(
        title="Fractions",
        segments=(segment(key="one", fallback=fallback),),
        confirmation_summary="Parsed.",
        review_notes=(),
    )


async def in_rollback(check):  # type: ignore[no-untyped-def]
    engine = create_engine(get_settings().database_url)
    connection = await engine.connect()
    transaction = await connection.begin()
    try:
        sessions = async_sessionmaker(bind=connection, expire_on_commit=False)
        async with sessions() as setup:
            token = uuid.uuid4().hex[:12]
            school = School(
                name="Downgrade Test School",
                school_code=f"dg-{token}",
                school_url_slug=f"dg-{token}",
            )
            setup.add(school)
            await setup.flush()
            author = User(
                school_id=school.id,
                role=UserRole.TEACHER,
                auth_method=AuthMethod.PIN,
                status=UserStatus.ACTIVE,
            )
            setup.add(author)
            await setup.flush()
        return await check(SqlAlchemyContentParsingRepository(sessions), sessions, author)
    finally:
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


REQUEST = ContentParseRequest(
    title="Fractions",
    source_type=LessonSourceType.TEXT,
    source_text="Fractions are parts of a whole.",
)


async def test_a_fallback_only_run_will_not_overwrite_a_written_lesson() -> None:
    async def check(repo, sessions, author):  # type: ignore[no-untyped-def]
        written = await repo.store(
            request=REQUEST,
            parsed=lesson(fallback=False),
            requested_by_user_id=author.id,
        )
        try:
            await repo.store(
                request=REQUEST,
                parsed=lesson(fallback=True),
                requested_by_user_id=author.id,
                existing_lesson_id=written.lesson_id,
            )
        except ValueError as error:
            refused = str(error)
        else:
            refused = ""
        return refused

    refused = await in_rollback(check)

    assert "refusing to replace" in refused
    # The refusal is raised before anything is deleted or rewritten, so the
    # lesson is left as it was. Not asserted on rows here: this harness runs
    # every store inside one outer transaction, so a row count after a
    # rollback would be measuring SQLAlchemy rather than the guard.


async def test_a_fallback_run_is_allowed_over_a_lesson_that_was_already_fallback() -> None:
    """There is nothing to protect, and refusing would strand the lesson."""

    async def check(repo, sessions, author):  # type: ignore[no-untyped-def]
        first = await repo.store(
            request=REQUEST,
            parsed=lesson(fallback=True),
            requested_by_user_id=author.id,
        )
        second = await repo.store(
            request=REQUEST,
            parsed=lesson(fallback=True),
            requested_by_user_id=author.id,
            existing_lesson_id=first.lesson_id,
        )
        return second.lesson_id

    assert await in_rollback(check) is not None


async def test_a_good_run_replaces_a_fallback_lesson() -> None:
    async def check(repo, sessions, author):  # type: ignore[no-untyped-def]
        first = await repo.store(
            request=REQUEST,
            parsed=lesson(fallback=True),
            requested_by_user_id=author.id,
        )
        await repo.store(
            request=REQUEST,
            parsed=lesson(fallback=False),
            requested_by_user_id=author.id,
            existing_lesson_id=first.lesson_id,
        )
        async with sessions() as session:
            return list(
                await session.scalars(
                    select(LessonSegment.review_reasons).where(
                        LessonSegment.lesson_id == first.lesson_id
                    )
                )
            )

    assert await in_rollback(check) == [[]]
