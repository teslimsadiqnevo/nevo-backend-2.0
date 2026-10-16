"""Repair metadata for the two reported E2E guides, preserving every section."""

import asyncio
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select

from nevo.api.frontend_unblockers import lesson_detail
from nevo.api.lesson_contracts import TextVariant, VisualVariant
from nevo.auth.entities import AuthPrincipal
from nevo.content_parsing.descriptions import clean_lesson_description
from nevo.core.config import get_settings
from nevo.db.models.account import School, User
from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.session import create_engine, create_session_factory


async def repair(session, lesson_id):
    lesson = await session.get(Lesson, lesson_id)
    school = await session.get(School, lesson.school_id)
    if school is None or "e2e" not in school.name.casefold():
        raise ValueError("Only the reported E2E lesson may be repaired")
    rows = list(
        await session.scalars(select(LessonSegment).where(LessonSegment.lesson_id == lesson.id))
    )
    changed = 0
    for row in rows:
        if row.visual_variant:
            try:
                VisualVariant.model_validate(row.visual_variant)
            except ValidationError:
                row.visual_variant = None
                changed += 1
        clean = (
            TextVariant.model_validate(row.text_variant).model_dump(by_alias=True, mode="json")
            if row.text_variant is not None
            else None
        )
        if clean != row.text_variant:
            row.text_variant = clean
            changed += 1
    lesson.description = clean_lesson_description(lesson.description)
    await session.flush()
    actor = await session.get(User, lesson.created_by_user_id)
    response = await lesson_detail(
        lesson.id,
        AuthPrincipal(user_id=actor.id, role=actor.role.value, session_id=uuid4()),
        session,
    )
    response.model_dump(mode="json", by_alias=True)
    print(
        f"{lesson_id}: repaired {changed} metadata fields; route response validates with "
        f"{len(response.segments)} sections"
    )
    print("Returned description:", response.description)


async def main():
    engine = create_engine(get_settings().database_url)
    try:
        async with create_session_factory(engine).begin() as session:
            for lesson_id in (
                UUID("4c2c9055-2b94-4fad-a8ef-5251c0a6ca3e"),
                UUID("d1d52470-c99d-4c40-8336-d6cec430bd4a"),
            ):
                await repair(session, lesson_id)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
