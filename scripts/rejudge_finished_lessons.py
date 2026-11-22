"""Re-judge which lessons are finished, on our evidence rather than the app's.

Lydia, 22 November: "18 is the number and the definition is the final check
taken and marked, stored as our decision rather than the app's claim.
Twenty-two of forty-one completed sittings having no recorded answer is the
whole argument. A profile built on a number that is half noise is worse than
a smaller honest one. Yes, re-judge the existing ones."

Her number and her principle disagree, and the dry run shows it. 18 is the
only one of the three rules that still consults the app's declaration, so
"our decision rather than the app's claim" cannot also be 18 - dropping the
claim gives 27. The rule is therefore an argument with no default, and the
dry run prints all three so the choice is made on the figures:

    app-and-check   the app says completed AND a check was marked
    ended-and-check a check was marked AND the sitting has ended
    check-only      a check was marked, full stop

"A check" means an in-lesson checkpoint or the end-of-lesson assessment,
server-marked. Strictly the *final* check - the end-of-lesson assessment
alone - gives 16 rather than 18, which is the other two-lesson gap between
her words and her number, and is reported too.

This writes verified_complete_at and never touches completion_status: the
app's declaration stays exactly as it is, because it is a record of what the
app said and we do not get to edit that.

Dry run unless --apply.
"""

from __future__ import annotations

import argparse
import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

#: A marked checkpoint or end-of-lesson assessment answer. The evidence is
#: that the child answered something we could mark, not that they got it
#: right - a wrong answer is still a lesson they did.
MARKED_CHECK = (
    "exists (select 1 from lesson_question_attempts a "
    "where a.session_id = s.id "
    "and a.source in ('checkpoint','assessment') "
    "and a.correct is not null)"
)

RULES = {
    "app-and-check": f"s.completion_status = 'completed' and {MARKED_CHECK}",
    "ended-and-check": f"s.ended_at is not null and {MARKED_CHECK}",
    "check-only": MARKED_CHECK,
}

#: Reported but not offered as a rule. It is the strictest reading of "the
#: final check" and it is not the number Lydia quoted, so choosing it would
#: be choosing against her figure without her saying so.
FINAL_CHECK_ONLY = (
    "s.completion_status = 'completed' and exists ("
    "select 1 from lesson_question_attempts a where a.session_id = s.id "
    "and a.source = 'assessment' and a.correct is not null)"
)


async def main(*, rule: str | None, apply: bool) -> None:
    url = os.environ["DATABASE_URL"].replace(
        "postgresql://", "postgresql+asyncpg://"
    ).split("?")[0]
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            total = (
                await connection.execute(text("select count(*) from lesson_sessions"))
            ).scalar_one()
            claimed = (
                await connection.execute(
                    text(
                        "select count(*) from lesson_sessions "
                        "where completion_status = 'completed'"
                    )
                )
            ).scalar_one()
            already = (
                await connection.execute(
                    text(
                        "select count(*) from lesson_sessions "
                        "where verified_complete_at is not null"
                    )
                )
            ).scalar_one()

            print(f"sittings in total:           {total}")
            print(f"the app calls completed:     {claimed}")
            print(f"already judged by us:        {already}")
            print()
            print("what each rule would count as finished:")
            for name, clause in RULES.items():
                count = (
                    await connection.execute(
                        text(f"select count(*) from lesson_sessions s where {clause}")
                    )
                ).scalar_one()
                marker = "  <- chosen" if name == rule else ""
                print(f"  {count:>4}  {name}{marker}")
            strict = (
                await connection.execute(
                    text(f"select count(*) from lesson_sessions s where {FINAL_CHECK_ONLY}")
                )
            ).scalar_one()
            print(f"  {strict:>4}  (end-of-lesson assessment only, not offered)")

        if rule is None:
            print("\nNo rule chosen, so nothing to write. Pass --rule to pick one.")
            return
        if not apply:
            print(f"\nDry run. Nothing written. Re-run with --rule {rule} --apply.")
            return

        async with engine.begin() as connection:
            clause = RULES[rule]
            # Set where the rule holds, and clear where it does not, so a
            # re-run is a judgement rather than an accumulation. Clearing
            # matters: a sitting that qualified under a looser rule must stop
            # counting when the rule tightens, or the number only ever grows.
            written = (
                await connection.execute(
                    text(
                        "update lesson_sessions s set verified_complete_at = "
                        "coalesce(s.verified_complete_at, s.ended_at, now()) "
                        f"where ({clause}) and s.verified_complete_at is null "
                        "returning s.id"
                    )
                )
            ).fetchall()
            cleared = (
                await connection.execute(
                    text(
                        "update lesson_sessions s set verified_complete_at = null "
                        f"where not ({clause}) and s.verified_complete_at is not null "
                        "returning s.id"
                    )
                )
            ).fetchall()
        print(f"\nrule: {rule}")
        print(f"  judged finished: {len(written)}")
        print(f"  judgement withdrawn: {len(cleared)}")
        print("  completion_status untouched, as it is a record of what the app said")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rule",
        choices=sorted(RULES),
        default=None,
        help="no default: the three rules give different numbers and the "
        "choice is a decision about what a finished lesson is",
    )
    parser.add_argument(
        "--apply", action="store_true", help="write the judgement (default: dry run)"
    )
    args = parser.parse_args()
    asyncio.run(main(rule=args.rule, apply=args.apply))
