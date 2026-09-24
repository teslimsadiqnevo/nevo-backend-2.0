"""Whether the database is at the revision this code was written against.

A deployment ran for two days with code that writes a column the database did
not have. Every lesson parse got as far as the INSERT, threw, and was
discarded - and nothing anywhere said the schema was behind. The service was
healthy, the API served the new field in its own schema document, and the only
symptom was that lessons stopped appearing.

So it is checked, and the check is cheap: the revision the migration files end
at, against the revision the database says it is at. A mismatch does not stop
the service - refusing to serve a school because one table is a column short
would turn a partial outage into a total one - but it stops being invisible.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

#: Where the migrations live, relative to the installed package.
MIGRATIONS = Path(__file__).resolve().parents[3] / "alembic" / "versions"


@lru_cache(maxsize=1)
def expected_revision() -> str | None:
    """The revision the migration files end at.

    Read from the files rather than from Alembic's own machinery, so this
    costs nothing at boot and cannot fail for a reason of its own. The head is
    the revision that nothing else lists as its ``down_revision``.
    """

    if not MIGRATIONS.is_dir():
        return None
    revisions: set[str] = set()
    superseded: set[str] = set()
    for path in MIGRATIONS.glob("*.py"):
        for line in path.read_text().splitlines():
            if line.startswith("revision:") or line.startswith("revision ="):
                revisions.add(_quoted(line))
            elif line.startswith("down_revision:") or line.startswith("down_revision ="):
                value = _quoted(line)
                if value:
                    superseded.add(value)
    heads = {value for value in revisions if value and value not in superseded}
    # More than one head is its own problem and not one this can answer.
    return heads.pop() if len(heads) == 1 else None


def _quoted(line: str) -> str:
    _, _, tail = line.partition("=")
    tail = tail.strip()
    for quote in ('"', "'"):
        if tail.startswith(quote) and tail.endswith(quote) and len(tail) > 1:
            return tail[1:-1]
    return ""


async def applied_revision(engine: AsyncEngine) -> str | None:
    """What the database says it is at, or None if it cannot be asked."""

    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT version_num FROM alembic_version"))
            return result.scalar()
    except Exception:
        # A database that cannot be reached is a louder problem than this one,
        # and it is already reported everywhere else.
        logger.warning("Could not read the applied migration revision", exc_info=True)
        return None


async def schema_state(engine: AsyncEngine) -> dict[str, str | None]:
    """What /health says about it, and what a boot log line says.

    Three answers rather than a boolean: up to date, behind, and unknown. A
    check that cannot tell "behind" from "could not look" is a check nobody
    should act on.
    """

    expected = expected_revision()
    applied = await applied_revision(engine)
    if expected is None or applied is None:
        state = "unknown"
    elif expected == applied:
        state = "up_to_date"
    else:
        state = "behind"
    return {"state": state, "expected": expected, "applied": applied}


async def warn_if_behind(engine: AsyncEngine) -> dict[str, str | None]:
    """Say it once at boot, loudly, in the log a deploy is read from."""

    state = await schema_state(engine)
    if state["state"] == "behind":
        logger.error(
            "DATABASE SCHEMA IS BEHIND THIS CODE: migrations end at %s, the database is at %s. "
            "Run 'alembic upgrade head'. Until then, anything written by a newer migration "
            "will fail at the first write and nowhere earlier.",
            state["expected"],
            state["applied"],
        )
    elif state["state"] == "unknown":
        logger.warning("Could not compare the database schema against this code")
    return state
