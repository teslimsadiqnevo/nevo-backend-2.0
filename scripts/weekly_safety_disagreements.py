"""The week's disagreements between the two checkers, while the lessons exist.

Lydia's first condition, 23 November: the review happens inside the retention
window, not at the end of the trial. If disagreements are collected for six
weeks and read at the end, the material behind the early ones has expired and
we are holding decisions we cannot examine - exactly the position shadow mode
was built to escape. So this runs weekly, over the week just gone, and once
somebody has written down which checker was right, only the adjudication needs
to survive. Nothing is kept any longer than it is kept today.

Pairing is by input_hash, which both rows already carry: the same chunk judged
twice gives one v1 row and one v2 row with the same hash. Neither row stores
the text, so the pairing costs no retention of its own.

--days defaults to 7. --all lists agreements too, which is how you check the
trial is actually running rather than silently producing nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

V1 = "child-safety-2026-10-v1"
V2 = "child-safety-2026-11-v2"

PAIRS = """
select  v1.input_hash,
        v1.created_at,
        v1.phase,
        v1.action       as v1_action,
        v2.action       as v2_action,
        v1.categories   as v1_categories,
        v2.categories   as v2_categories,
        v1.reason       as v1_reason,
        v2.reason       as v2_reason,
        v1.lesson_context->>'lesson_id'  as lesson_id,
        v1.lesson_context->>'upload_id'  as upload_id,
        v1.school_id,
        v1.actor_user_id,
        (v1.review_material is not null or v1.allowed_material is not null) as text_kept,
        v1.material_expires_at
from        content_safety_events v1
join        content_safety_events v2
       on   v2.input_hash = v1.input_hash
      and   v2.policy_version = :v2
      and   v2.created_at between v1.created_at - interval '10 minutes'
                              and v1.created_at + interval '10 minutes'
where       v1.policy_version = :v1
  and       v1.created_at >= :since
order by    v1.created_at
"""

REFUSED = {"block", "safeguard", "hold"}


def verdict(action: str) -> str:
    return "refused" if action in REFUSED else "accepted"


async def main(*, days: int, show_all: bool) -> None:
    url = os.environ["DATABASE_URL"].replace(
        "postgresql://", "postgresql+asyncpg://"
    ).split("?")[0]
    since = datetime.now(UTC) - timedelta(days=days)
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(PAIRS), {"v1": V1, "v2": V2, "since": since}
                )
            ).all()
            checked = (
                await connection.execute(
                    text(
                        "select count(*) from content_safety_events "
                        "where policy_version = :v1 and created_at >= :since"
                    ),
                    {"v1": V1, "since": since},
                )
            ).scalar_one()

        print(f"week ending {datetime.now(UTC):%Y-%m-%d}, looking back {days} days")
        print(f"  checks run by the live checker : {checked}")
        print(f"  of those, also judged by v2    : {len(rows)}")

        if checked and not rows:
            print("\n  Nothing was shadowed. Either SAFETY_POLICY_V2_SHADOW is off, or")
            print("  the material was on phases v2 does not cover (the image phases).")
        if not checked:
            print("\n  No lessons were checked at all this week, so the trial learned")
            print("  nothing. Shadow mode only sees real uploads; a quiet week is a")
            print("  week the clock did not move.")

        disagreements = [r for r in rows if verdict(r.v1_action) != verdict(r.v2_action)]
        print(f"  disagreements                  : {len(disagreements)}")
        print()

        shown = rows if show_all else disagreements
        if not shown:
            print("Nothing to adjudicate." if rows else "Nothing to show.")
        for r in shown:
            flag = "  <-- ADJUDICATE" if verdict(r.v1_action) != verdict(r.v2_action) else ""
            print(f"[{r.created_at:%a %d %b %H:%M}] {r.phase}{flag}")
            print(f"    live (v1): {r.v1_action:<10} {list(r.v1_categories or [])}")
            print(f"      shadow : {r.v2_action:<10} {list(r.v2_categories or [])}")
            print(f"    v1 says  : {r.v1_reason or '(no reason given)'}")
            print(f"    v2 says  : {r.v2_reason or '(no reason given)'}")
            where = r.lesson_id or r.upload_id or "NOT RECORDED"
            print(f"    lesson/upload: {where}   school: {r.school_id}")
            if r.text_kept:
                print(f"    text still held, expires {r.material_expires_at:%d %b}")
            else:
                print("    text NOT held - judge from the reasons above, or not at all")
            print()

        if disagreements:
            print("Lydia's rule, 23 November: v2 ships if it accepts lessons v1 refused")
            print("and the review agrees they were safe. One acceptance of something")
            print("v1 refused that the review judges UNSAFE and v2 is finished,")
            print("whatever it scores on everything else.")
            fatal = [
                r for r in disagreements
                if r.v1_action in REFUSED and r.v2_action not in REFUSED
            ]
            print(f"\n  candidates for that test this week: {len(fatal)}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument(
        "--all", action="store_true", dest="show_all",
        help="list agreements too, to confirm the trial is running at all",
    )
    args = parser.parse_args()
    asyncio.run(main(days=args.days, show_all=args.show_all))
