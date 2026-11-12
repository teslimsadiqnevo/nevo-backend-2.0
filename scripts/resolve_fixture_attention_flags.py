"""Close the seeded attention flags in the E2E test school.

Spare Teacher's Home was showing twenty cards reading "A fixture flag for the
E2E tenant.", raised between 25 September and 2 October. There are 240 of
them, 140 still open, all in the E2E school and all carrying that one
description.

Resolved rather than deleted. attention_flags is where a concern about a child
is recorded, and a script that deletes rows from it is a script that could
delete a real one. Marking them resolved clears the teacher's Home - which now
shows open flags only - and leaves the record intact.

Scoped three ways, and refuses to run if any of them fails to hold: the E2E
school, that exact description, and flags raised before October. Dry run
unless --apply.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nevo.db.models.account import User
from nevo.db.models.attention_flag import AttentionFlag

#: The E2E test school. Nothing outside it is touched.
TEST_SCHOOL_ID = UUID("c5cd0a8d-043c-4f97-aad2-4a724a877a29")

#: The exact description the seed wrote. Not a wildcard: a substring match
#: could reach a real flag that happened to mention a fixture.
DESCRIPTION = "A fixture flag for the E2E tenant."

#: Nothing raised in the demo period. The seeded ones are all September.
RAISED_BEFORE = date(2026, 10, 3)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the change")
    args = parser.parse_args()

    url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    try:
        in_scope = (
            AttentionFlag.description == DESCRIPTION,
            AttentionFlag.generated_at < datetime(2026, 10, 3, tzinfo=UTC),
            AttentionFlag.student_id.in_(select(User.id).where(User.school_id == TEST_SCHOOL_ID)),
        )

        async with sessions() as session:
            total = await session.scalar(select(func.count(AttentionFlag.id)).where(*in_scope))
            still_open = await session.scalar(
                select(func.count(AttentionFlag.id)).where(
                    *in_scope,
                    AttentionFlag.acknowledged_at.is_(None),
                    AttentionFlag.resolved_at.is_(None),
                )
            )
            # The safety check: anything matching that description outside the
            # test school means the scope is wrong and this must not run.
            stray = await session.scalar(
                select(func.count(AttentionFlag.id)).where(
                    AttentionFlag.description == DESCRIPTION,
                    AttentionFlag.student_id.notin_(
                        select(User.id).where(User.school_id == TEST_SCHOOL_ID)
                    ),
                )
            )
            print(f"in scope        {total}")
            print(f"still open      {still_open}")
            print(f"outside the E2E school with this description: {stray}")
            if stray:
                raise SystemExit(
                    "Refusing to run: that description exists outside the test "
                    "school, so this scope would reach flags it should not."
                )
            if not still_open:
                print("nothing open; nothing to do")
                return
            if not args.apply:
                print()
                print(f"dry run: would resolve {still_open}. Re-run with --apply.")
                return

        async with sessions.begin() as session:
            await session.execute(
                update(AttentionFlag)
                .where(
                    *in_scope,
                    AttentionFlag.acknowledged_at.is_(None),
                    AttentionFlag.resolved_at.is_(None),
                )
                .values(resolved_at=now)
            )

        async with sessions() as session:
            left = await session.scalar(
                select(func.count(AttentionFlag.id)).where(
                    *in_scope,
                    AttentionFlag.acknowledged_at.is_(None),
                    AttentionFlag.resolved_at.is_(None),
                )
            )
            kept = await session.scalar(select(func.count(AttentionFlag.id)).where(*in_scope))
        print()
        print(f"resolved        {still_open}")
        print(f"still open      {left}")
        print(f"rows kept       {kept} (resolved, not deleted)")
        sys.exit(0 if left == 0 else 1)
    finally:
        await engine.dispose()


asyncio.run(main())
