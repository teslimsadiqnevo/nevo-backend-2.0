"""Repair only the E2E Z-guide response metadata, preserving all 45 sections."""

import asyncio
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select

from nevo.api.frontend_unblockers import lesson_detail
from nevo.api.lesson_contracts import VisualVariant, canonical_authorship
from nevo.auth.entities import AuthPrincipal
from nevo.core.config import get_settings
from nevo.db.models.account import School, User
from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.session import create_engine, create_session_factory


def fix_authorship(value):
    if isinstance(value, dict):
        return {
            key: canonical_authorship(item) if key == "authoredBy" else fix_authorship(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [fix_authorship(item) for item in value]
    return value


async def main():
    engine = create_engine(get_settings().database_url)
    try:
        async with create_session_factory(engine).begin() as session:
            lesson = await session.get(Lesson, UUID("4c2c9055-2b94-4fad-a8ef-5251c0a6ca3e"))
            school = await session.get(School, lesson.school_id)
            if school is None or "e2e" not in school.name.casefold():
                raise ValueError("Only the reported E2E lesson may be repaired")
            rows = list(
                await session.scalars(
                    select(LessonSegment).where(LessonSegment.lesson_id == lesson.id)
                )
            )
            changed = 0
            for row in rows:
                if row.visual_variant:
                    try:
                        VisualVariant.model_validate(row.visual_variant)
                    except ValidationError:
                        row.visual_variant = None
                        changed += 1
                clean = fix_authorship(row.text_variant)
                if clean != row.text_variant:
                    row.text_variant = clean
                    changed += 1
            await session.flush()
            actor = await session.get(User, lesson.created_by_user_id)
            response = await lesson_detail(
                lesson.id,
                AuthPrincipal(user_id=actor.id, role=actor.role.value, session_id=uuid4()),
                session,
            )
            response.model_dump(mode="json", by_alias=True)
            print(
                f"Repaired {changed} metadata fields; complete route response validates with "
                f"{len(response.segments)} sections"
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
