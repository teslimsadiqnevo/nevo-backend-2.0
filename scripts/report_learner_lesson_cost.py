"""What one lesson cost, and what one learner's share of it is.

Lydia's rule, 22 November: preparation cost is assigned whole to the learner
on the individual route, and split across the class on the school route,
"because that is what actually happens to the money in each case".

Preparation happens when a file is uploaded, before any child exists, so
those calls carry a lesson and no learner. Serving calls - re-teaches,
guidance, checks - carry both. This report puts the two together under her
rule.

WHAT THIS CANNOT YET INCLUDE, and it is the largest part.

Images cost about 17 cents each and more in total than every text call we
have ever made. They are recorded in media_usage_events with a run id that
is a fresh UUID per image, created by the tracked_generation decorator - it
reaches no lesson, no segment and no upload. So media spend cannot be
attributed to a lesson at all, and the figures below are text only.

That is a fourth fix, not one of the three that were asked for, and it is
the one that matters most: a per-learner cost that omits images omits the
bill. The report says so on every run rather than leaving a reader to
assume the number is complete. Fixing it means carrying a lesson id on the
media Run, which both the audio and the visuals service already know when
they open one.

Historic rows carry no lesson either way: lesson_id arrived on
ai_gateway_calls on 20 November and was deliberately not backfilled, since
the only way to guess one is to match timestamps. So this reports on lessons
prepared after that date.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

INDIVIDUAL = "individual"
SCHOOL = "school"


async def main(*, lesson_id: UUID, route: str, learner_id: UUID | None) -> None:
    url = os.environ["DATABASE_URL"].replace(
        "postgresql://", "postgresql+asyncpg://"
    ).split("?")[0]
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            prep = (
                await connection.execute(
                    text(
                        "select count(*) as calls, "
                        "coalesce(sum(estimated_cost_usd), 0) as cost "
                        "from ai_gateway_calls "
                        "where lesson_id = :lesson and student_id is null"
                    ),
                    {"lesson": lesson_id},
                )
            ).one()

            # How many learners the preparation is spread over. On the school
            # route that is the class the lesson is assigned to; a lesson
            # assigned to several classes is spread over all of them, because
            # it was prepared once for all of them.
            assigned = (
                await connection.execute(
                    text(
                        "select count(distinct student_id) from lesson_assignments "
                        "where lesson_id = :lesson and status <> 'cancelled'"
                    ),
                    {"lesson": lesson_id},
                )
            ).scalar_one()

            serving = (
                await connection.execute(
                    text(
                        "select count(*) as calls, "
                        "coalesce(sum(estimated_cost_usd), 0) as cost "
                        "from ai_gateway_calls "
                        "where lesson_id = :lesson "
                        "and (cast(:learner as uuid) is null "
                        "     or student_id = cast(:learner as uuid)) "
                        "and student_id is not null"
                    ),
                    {"lesson": lesson_id, "learner": learner_id},
                )
            ).one()

            media = (
                await connection.execute(
                    text(
                        # Every row, not only the generation wrappers: those
                        # carry no cost, and filtering on them reported media
                        # spend as zero - the exact understatement this
                        # section exists to prevent.
                        #
                        # Priced and unpriced are counted apart, because the
                        # ledger distinguishes them and so should this: a job
                        # poll costs a true zero, while a synthesis call with
                        # no published rate is unknown. Adding them together
                        # is how an unknown becomes a nothing.
                        "select medium, "
                        "coalesce(sum(estimated_cost), 0) as cost, "
                        "count(*) filter (where estimated_cost is null) as unpriced "
                        "from media_usage_events group by 1 order by 2 desc"
                    )
                )
            ).all()

        prep_cost = Decimal(prep[1])
        serve_cost = Decimal(serving[1])

        print(f"lesson   {lesson_id}")
        print(f"route    {route}")
        print(f"learner  {learner_id or '(all learners on this lesson)'}")
        print()
        print(f"preparation: {prep[0]} call(s), ${prep_cost:.4f} in total")

        if route == INDIVIDUAL:
            share = prep_cost
            print("  assigned whole to this learner, per the individual route")
        else:
            learners = max(assigned, 1)
            share = (prep_cost / learners).quantize(Decimal("0.000001"))
            print(f"  split across {learners} learner(s) assigned this lesson")
            if assigned == 0:
                print("  (nobody is assigned it yet, so this is the undivided figure)")

        print(f"  this learner's share: ${share:.6f}")
        print()
        print(f"serving:     {serving[0]} call(s), ${serve_cost:.4f}")
        print()
        print(f"TEXT TOTAL for this learner: ${share + serve_cost:.6f}")

        print()
        print("NOT INCLUDED - media, which is the larger part:")
        for medium, cost, unpriced in media:
            line = f"  {medium}: ${Decimal(cost):.4f} priced"
            if unpriced:
                line += f", {unpriced} call(s) with no published rate"
            print(line)
        print(
            "  Media carries no lesson id, so none of this can be attributed to\n"
            "  one lesson or one learner. Images cost more in total than every\n"
            "  text call ever made, so the figure above is not the answer to\n"
            "  'what did this lesson cost' - it is the text part of it."
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lesson", required=True, type=UUID)
    parser.add_argument(
        "--route",
        required=True,
        choices=(INDIVIDUAL, SCHOOL),
        help="individual assigns preparation whole to the learner; school "
        "splits it across everyone assigned the lesson",
    )
    parser.add_argument(
        "--learner",
        type=UUID,
        default=None,
        help="omit to total the serving calls for every learner on the lesson",
    )
    args = parser.parse_args()
    asyncio.run(
        main(lesson_id=args.lesson, route=args.route, learner_id=args.learner)
    )
