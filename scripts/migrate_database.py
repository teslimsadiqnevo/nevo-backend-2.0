"""Copy the live database to a new one, and prove the copy is faithful.

Written for the move off Supabase to Render Postgres, but it is not specific
to either: it copies the ``public`` schema between any two Postgres databases
that are already at the same Alembic revision.

The approach is deliberately not pg_dump. The target's schema is built by
``alembic upgrade head`` first, so it provably matches the code rather than
matching whatever the source had accumulated, and none of Supabase's roles,
grants, RLS policies or internal schemas come along. This script then moves
rows only.

Three things it does that a loop over tables would not:

  * It copies in ``Base.metadata.sorted_tables`` order, which is a topological
    sort, so every foreign key is satisfied without the constraints being
    switched off. They stay on throughout and are part of the proof.

  * It disables user triggers on the target for the copy. This is not an
    optimisation. ``users`` carries create_pending_consent_for_roster_student,
    which fires on insert and manufactures consent rows; copying users would
    invent them, and copying the real consent_records on top would collide -
    in the table that decides whether a child may start a lesson. Forty more
    tables carry the retention guard. They are re-enabled afterwards and the
    count is checked, because leaving them off would silently disarm the
    retention guards on the live database.

  * It verifies by comparing counts per table rather than reporting success.

Usage, with both URLs in the environment so neither can be confused with
DATABASE_URL:

    export SOURCE_DATABASE_URL=...   # the live database
    export TARGET_DATABASE_URL=...   # the new, already-migrated one

    python scripts/migrate_database.py            # plan: reads only
    python scripts/migrate_database.py --copy     # do it
    python scripts/migrate_database.py --verify   # compare the two

Nothing is written without --copy.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Callable

from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import create_async_engine

#: Alembic owns this one; the target already has the right value.
SKIP = frozenset({"alembic_version"})

#: Tables the migrations themselves seed, so a freshly built target is not
#: empty: 50 prompt templates, 32 subjects, 4 tiers.
#:
#: They are emptied before being copied, rather than skipped. The seed is
#: whatever the migrations said at the time; the live database is what
#: production has actually been running, prompt edits included, and that is
#: the thing being moved. Skipping them would quietly ship the seed instead.
#:
#: Rows anywhere else on the target mean it is not a fresh build, and the
#: preflight refuses - so a migration that starts seeding a fourth table
#: fails loudly here rather than duplicating it.
SEEDED_BY_MIGRATIONS = frozenset(
    {"ai_prompt_templates", "canonical_subjects", "subscription_tiers"}
)

#: Rows per INSERT. Large enough that a 71 MB database is a few minutes,
#: small enough that one failure does not lose much work.
BATCH = 500

#: The source may be a pooler that stalls or drops a connection, so reads
#: retry. Writes do not: a half-written table should stop and be looked at.
READ_ATTEMPTS = 4

CONNECT_ARGS = {"statement_cache_size": 0, "command_timeout": 300, "timeout": 30}


def _engine(url: str):
    return create_async_engine(
        url.replace("postgresql://", "postgresql+asyncpg://", 1),
        pool_pre_ping=True,
        connect_args=CONNECT_ARGS,
    )


def _host(url: str) -> str:
    from sqlalchemy.engine import make_url

    parsed = make_url(url.replace("postgresql://", "postgresql+asyncpg://", 1))
    return f"{parsed.host}:{parsed.port or 5432}/{parsed.database}"


async def _retry(work: Callable, what: str):
    last: Exception | None = None
    for attempt in range(READ_ATTEMPTS):
        try:
            return await work()
        except Exception as error:  # the source is remote; keep trying
            last = error
            print(f"   retrying {what} after {type(error).__name__}")
            await asyncio.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{what} failed after {READ_ATTEMPTS} attempts") from last


def _tables():
    """Every public table the models know about, in dependency order."""
    import importlib
    import pkgutil

    import nevo.db.models as models
    from nevo.db.base import Base

    for found in pkgutil.iter_modules(models.__path__):
        importlib.import_module(f"nevo.db.models.{found.name}")
    return [table for table in Base.metadata.sorted_tables if table.name not in SKIP]


def _self_references(table) -> list[str]:
    """Columns in this table that point at this same table.

    Three of them exist: auth_sessions.replaced_by_session_id,
    lesson_sessions.rerouted_from_session_id and
    teacher_class_assignments.replaced_by_assignment_id.

    Sorting tables topologically orders the tables, not the rows inside one,
    so a row can reference a sibling that has not been inserted yet - which
    is a foreign key violation part-way through a table that looked fine in
    testing. All three are nullable, so they are inserted empty and filled in
    afterwards. That keeps every other constraint enforced throughout, and
    needs no superuser, which a managed Postgres will not give us anyway.
    """
    return sorted(
        {fk.parent.name for fk in table.foreign_keys if fk.column.table.name == table.name}
    )


async def _restore_self_references(target, pending) -> int:
    """Second pass: put back the links that were nulled to get the rows in."""
    restored = 0
    for table, updates in pending:
        key = next(iter(table.primary_key.columns))
        async with target.begin() as connection:
            for identity, values in updates:
                await connection.execute(table.update().where(key == identity).values(**values))
                restored += 1
    return restored


async def _revision(engine) -> str:
    """The Alembic revision, or "" when the schema has not been built yet.

    Returning empty rather than raising, so a target nobody has migrated
    produces the sentence that says what to do instead of a stack trace.
    """
    try:
        async with engine.connect() as connection:
            return await connection.scalar(text("select version_num from alembic_version")) or ""
    except Exception:
        return ""


async def _encoding(engine) -> str:
    async with engine.connect() as connection:
        return await connection.scalar(
            text(
                "select pg_encoding_to_char(encoding) from pg_database "
                "where datname = current_database()"
            )
        )


async def _trigger_count(engine) -> int:
    async with engine.connect() as connection:
        return await connection.scalar(
            text(
                "select count(*) from pg_trigger t "
                "join pg_class c on c.oid = t.tgrelid "
                "join pg_namespace n on n.oid = c.relnamespace "
                "where not t.tgisinternal and n.nspname = 'public'"
            )
        )


async def _counts(engine, tables) -> dict[str, int]:
    found: dict[str, int] = {}
    async with engine.connect() as connection:
        for table in tables:
            found[table.name] = await connection.scalar(select(func.count()).select_from(table))
    return found


async def _preflight(source, target, tables, *, force: bool) -> dict[str, int]:
    """Refuse to copy into a database that is not ready for it."""
    source_revision, target_revision = await _revision(source), await _revision(target)
    print(f"source revision   {source_revision}")
    print(f"target revision   {target_revision}")
    if not source_revision:
        raise SystemExit("Refusing: the source has no alembic_version. Is that URL right?")
    if not target_revision:
        raise SystemExit(
            "Refusing: the target has no schema yet. Build it first, so it matches "
            "the code rather than whatever the source accumulated:\n\n"
            "    DATABASE_URL=<target> NEVO_ALLOW_DATABASE_TARGET=1 alembic upgrade head"
        )
    if source_revision != target_revision:
        raise SystemExit(
            f"Refusing: source is at {source_revision} and target at "
            f"{target_revision}. Bring the target to the same revision first."
        )

    source_encoding, target_encoding = await _encoding(source), await _encoding(target)
    print(f"source encoding   {source_encoding}")
    print(f"target encoding   {target_encoding}")
    if target_encoding != source_encoding:
        raise SystemExit(
            f"Refusing: the source is {source_encoding} and the target is "
            f"{target_encoding}. Lesson text is not ASCII, and a JSONB column "
            "holding a non-ASCII character fails with 'unsupported Unicode "
            "escape sequence' part-way through the copy - which reads like "
            "corrupt data and is really the database being created wrong. "
            "Create the target with UTF8."
        )

    source_triggers, target_triggers = await _trigger_count(source), await _trigger_count(target)
    print(f"source triggers   {source_triggers}")
    print(f"target triggers   {target_triggers}")
    if source_triggers != target_triggers:
        raise SystemExit(
            "Refusing: the two databases have different numbers of triggers, so "
            "the target's schema is not the source's. Check the migration ran "
            "completely."
        )

    existing = await _counts(target, tables)
    seeded = {name: n for name, n in existing.items() if n and name in SEEDED_BY_MIGRATIONS}
    if seeded:
        print(f"seeded by migrations: {', '.join(f'{k} {v}' for k, v in sorted(seeded.items()))}")
        print("   these are emptied and replaced from the source")
    occupied = {name: n for name, n in existing.items() if n and name not in SEEDED_BY_MIGRATIONS}
    if occupied and not force:
        print()
        for name, n in sorted(occupied.items(), key=lambda row: -row[1])[:10]:
            print(f"   {name}: {n}")
        raise SystemExit(
            f"\nRefusing: the target already holds rows in {len(occupied)} table(s). "
            "Copying into it would duplicate or collide. Start from an empty "
            "database, or pass --force if you know why these are there."
        )
    return source_triggers


async def _set_triggers(engine, tables, *, enabled: bool) -> None:
    word = "ENABLE" if enabled else "DISABLE"
    async with engine.begin() as connection:
        for table in tables:
            await connection.execute(text(f'ALTER TABLE "{table.name}" {word} TRIGGER USER'))


async def copy(source, target, tables, *, force: bool) -> None:
    expected_triggers = await _preflight(source, target, tables, force=force)

    print("\ndisabling user triggers on the target")
    await _set_triggers(target, tables, enabled=False)

    copied: dict[str, int] = {}
    empty: list[str] = []
    #: (table, [(primary key, {column: value})]) for the second pass.
    pending: list = []
    try:
        for table in tables:

            async def read(current=table):
                async with source.connect() as connection:
                    result = await connection.execute(select(current))
                    return [dict(row) for row in result.mappings()]

            rows = await _retry(read, f"reading {table.name}")
            if not rows:
                empty.append(table.name)
                continue
            links = _self_references(table)
            if links:
                key = next(iter(table.primary_key.columns)).name
                held = [
                    (row[key], {column: row[column] for column in links})
                    for row in rows
                    if any(row[column] is not None for column in links)
                ]
                if held:
                    pending.append((table, held))
                    print(f"   {table.name:<40} {len(rows)} (+{len(held)} links deferred)")
                rows = [{**row, **dict.fromkeys(links)} for row in rows]
            async with target.begin() as connection:
                if table.name in SEEDED_BY_MIGRATIONS:
                    # One transaction, so the table is never half-seeded and
                    # half-copied if this fails part-way.
                    await connection.execute(table.delete())
                for start in range(0, len(rows), BATCH):
                    await connection.execute(insert(table), rows[start : start + BATCH])
            copied[table.name] = len(rows)
            if not _self_references(table):
                print(f"   {table.name:<40} {len(rows)}", flush=True)
        if pending:
            restored = await _restore_self_references(target, pending)
            print(f"\nrestored {restored} self-referencing links")
    finally:
        # Always, including after a failure part-way: a target left with its
        # triggers off is a database whose retention guards do not fire.
        print("\nre-enabling user triggers")
        await _set_triggers(target, tables, enabled=True)

    restored = await _trigger_count(target)
    print(f"triggers restored {restored} (expected {expected_triggers})")
    if restored != expected_triggers:
        raise SystemExit(
            "The trigger count does not match after re-enabling. Do not cut over: "
            "the retention guards may not fire."
        )
    print(f"\ncopied {sum(copied.values())} rows across {len(copied)} tables")
    print(f"{len(empty)} tables were empty in the source")


async def verify(source, target, tables) -> int:
    """Compare the two, table by table, and say where they differ."""
    source_counts = await _counts(source, tables)
    target_counts = await _counts(target, tables)

    differences = [
        (name, source_counts[name], target_counts[name])
        for name in source_counts
        if source_counts[name] != target_counts[name]
    ]
    total_source = sum(source_counts.values())
    total_target = sum(target_counts.values())
    print(f"rows   source {total_source}   target {total_target}")
    print(f"tables compared {len(source_counts)}")

    if differences:
        print("\nTABLES THAT DIFFER:")
        for name, want, got in differences:
            print(f"   {name:<40} source {want}  target {got}")
    else:
        print("every table matches")

    source_revision, target_revision = await _revision(source), await _revision(target)
    source_triggers, target_triggers = await _trigger_count(source), await _trigger_count(target)
    print(f"\nrevision   source {source_revision}   target {target_revision}")
    print(f"triggers   source {source_triggers}   target {target_triggers}")

    ok = (
        not differences
        and source_revision == target_revision
        and source_triggers == target_triggers
    )
    print("\nthe copy is faithful" if ok else "\nDO NOT CUT OVER - see above")
    return 0 if ok else 1


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--copy", action="store_true", help="copy the rows")
    group.add_argument("--verify", action="store_true", help="compare the two databases")
    parser.add_argument(
        "--force",
        action="store_true",
        help="copy even though the target already holds rows",
    )
    args = parser.parse_args()

    try:
        source_url = os.environ["SOURCE_DATABASE_URL"]
        target_url = os.environ["TARGET_DATABASE_URL"]
    except KeyError as missing:
        raise SystemExit(
            f"Set {missing}. Both URLs are named explicitly so that "
            "neither can be confused with DATABASE_URL."
        ) from None

    if _host(source_url) == _host(target_url):
        raise SystemExit("Refusing: the source and the target are the same database.")

    print(f"source   {_host(source_url)}")
    print(f"target   {_host(target_url)}")
    print()

    source, target = _engine(source_url), _engine(target_url)
    tables = _tables()
    try:
        if args.copy:
            await copy(source, target, tables, force=args.force)
            print()
            sys.exit(await verify(source, target, tables))
        if args.verify:
            sys.exit(await verify(source, target, tables))

        # The default: read everything, write nothing.
        await _preflight(source, target, tables, force=True)
        counts = await _counts(source, tables)
        live = {name: n for name, n in counts.items() if n}
        print(f"\nwould copy {sum(live.values())} rows across {len(live)} tables")
        for name, n in sorted(live.items(), key=lambda row: -row[1])[:12]:
            print(f"   {name:<40} {n}")
        print(f"   ... and {max(0, len(live) - 12)} smaller tables")
        print("\nnothing written. Re-run with --copy.")
    finally:
        await source.dispose()
        await target.dispose()


asyncio.run(main())
