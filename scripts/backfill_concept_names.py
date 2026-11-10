"""Rewrite concept names that are keys rather than names.

Concept rows hold the name the model wrote, and the model sometimes writes an
identifier: conductorVsInsulator, stack_pitfall, periodGroupDefinition. Every
read of concept.name now humanises on the way out, so no child or parent sees
one today. This makes the stored rows match, so the key stops travelling at
all - into exports, into a teacher's review screen, into anything written
before the read-side fix existed.

Dry run unless --apply. Prints every change for eyeballing first, because a
rename nobody reviewed is how a real name gets tidied into a wrong one.

    python scripts/backfill_concept_names.py
    python scripts/backfill_concept_names.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nevo.content_parsing.concept_names import readable_concept_name
from nevo.db.models.frontend_support import Concept


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the changes")
    args = parser.parse_args()

    url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            rows = list(await session.scalars(select(Concept)))
            changes = [
                (row, readable_concept_name(row.name))
                for row in rows
                if readable_concept_name(row.name) and readable_concept_name(row.name) != row.name
            ]
            print(f"{len(rows)} concepts, {len(changes)} holding a key rather than a name")
            print()
            for row, better in changes:
                print(f"  {row.name!r}")
                print(f"    -> {better!r}")
            if not changes:
                print("nothing to do")
                return
            if not args.apply:
                print()
                print("dry run; re-run with --apply to write these")
                return

        async with sessions.begin() as session:
            for row, better in changes:
                stored = await session.get(Concept, row.id)
                if stored is not None:
                    stored.name = better

        async with sessions() as session:
            left = [
                row.name
                for row in await session.scalars(select(Concept))
                if readable_concept_name(row.name) and readable_concept_name(row.name) != row.name
            ]
        print()
        print(f"rewrote {len(changes)}; {len(left)} still holding a key")
        if left:
            for name in left[:10]:
                print(f"  {name!r}")
        sys.exit(0 if not left else 1)
    finally:
        await engine.dispose()


asyncio.run(main())
