"""Price the audio we have already synthesised, once YarnGPT gives a rate.

Lydia asked for "an audio price" as the third of three fixes before the
per-learner cost run. There is nothing broken to fix: the ledger records the
character count on every synthesis call, and an unpriced provider is stored
as NULL rather than as zero - `estimate()` says so in its own first line,
"Unknown is NULL, never a guessed zero or an invoice claim". What is missing
is only the rate, which YarnGPT does not publish.

So this is the piece that makes the rate worth having the moment it arrives.
Every synthesis row carries its characters, so the cost of everything
already spoken is arithmetic rather than a migration: 11,586 characters as
of 22 November, across 57 calls.

Future rows price themselves once MEDIA_PRICING_JSON carries the rate:

    {"yarngpt:tts": {"currency": "NGN", "per_1000_characters": "<rate>"}}

This script is for the rows recorded before that, and it refuses to invent a
rate: --rate is required and there is no default. Dry run unless --apply.

Deliberately no backfill of rows whose characters were never recorded - the
job polls and voice-catalogue reads carry none, and they cost nothing to
make. Only synthesis is priced, which is the only operation that bills.

And only synthesis that *succeeded*. Twenty-two calls returned an HTTP error
carrying 10,932 characters between them; whether YarnGPT billed for those is
their answer, not ours to assume. Pricing them would overstate the figure by
almost half, and a cost somebody prices against must not be inflated by work
that may never have been charged. They are reported separately so the
question stays visible, and --include-failed prices them once we know.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main(
    *, rate: Decimal, currency: str, apply: bool, include_failed: bool
) -> None:
    url = os.environ["DATABASE_URL"].replace(
        "postgresql://", "postgresql+asyncpg://"
    ).split("?")[0]
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        "select count(*) as calls, "
                        "coalesce(sum((usage->>'characters')::bigint), 0) as characters "
                        "from media_usage_events "
                        "where medium = 'audio' and operation = 'synthesis' "
                        "and estimated_cost is null "
                        "and (usage->>'characters') is not null "
                        "and (status = 'succeeded' or :include_failed)"
                    ),
                    {"include_failed": include_failed},
                )
            ).one()
            failed = (
                await connection.execute(
                    text(
                        "select count(*) as calls, "
                        "coalesce(sum((usage->>'characters')::bigint), 0) as characters "
                        "from media_usage_events "
                        "where medium = 'audio' and operation = 'synthesis' "
                        "and status <> 'succeeded' "
                        "and (usage->>'characters') is not null"
                    )
                )
            ).one()
        calls, characters = rows[0], rows[1]
        cost = (Decimal(characters) * rate / 1000).quantize(Decimal("0.0001"))
        print(f"unpriced synthesis calls: {calls}")
        print(f"characters:               {characters:,}")
        print(f"rate:                     {rate} per 1000 characters ({currency})")
        print(f"cost of everything spoken so far: {cost} {currency}")
        if not include_failed and failed[0]:
            would = (Decimal(failed[1]) * rate / 1000).quantize(Decimal("0.0001"))
            print(
                f"\nnot priced: {failed[0]} failed call(s) carrying {failed[1]:,} "
                f"characters, which would add {would} {currency}. Whether YarnGPT "
                f"billed for those is their answer. --include-failed once known."
            )

        if not apply:
            print("\nDry run. Nothing written. Re-run with --apply.")
            return

        async with engine.begin() as connection:
            written = (
                await connection.execute(
                    text(
                        "update media_usage_events set "
                        "estimated_cost = ((usage->>'characters')::numeric * :rate / 1000), "
                        "currency = :currency, "
                        # The rate this row was priced at, kept beside the
                        # figure. A later rate change must not silently
                        # restate what we thought last month's audio cost.
                        "pricing = pricing || jsonb_build_object("
                        "  'per_1000_characters', :rate_text, 'currency', :currency) "
                        "where medium = 'audio' and operation = 'synthesis' "
                        "and estimated_cost is null "
                        "and (usage->>'characters') is not null "
                        "and (status = 'succeeded' or :include_failed) "
                        "returning id"
                    ),
                    {
                        "rate": rate,
                        "rate_text": str(rate),
                        "currency": currency,
                        "include_failed": include_failed,
                    },
                )
            ).fetchall()
        print(f"\npriced {len(written)} row(s) at {rate} per 1000 characters")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rate",
        required=True,
        type=Decimal,
        help="price per 1000 characters, from YarnGPT's own quote. No default: "
        "a guessed rate on a cost figure somebody prices against is worse "
        "than no figure.",
    )
    parser.add_argument("--currency", default="NGN", help="defaults to NGN")
    parser.add_argument(
        "--apply", action="store_true", help="write the figures (default: dry run)"
    )
    parser.add_argument(
        "--include-failed",
        action="store_true",
        help="also price synthesis calls that returned an error, once YarnGPT "
        "has confirmed it bills for them",
    )
    args = parser.parse_args()
    asyncio.run(
        main(
            rate=args.rate,
            currency=args.currency,
            apply=args.apply,
            include_failed=args.include_failed,
        )
    )
