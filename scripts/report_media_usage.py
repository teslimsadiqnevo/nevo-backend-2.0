"""Operator-only media accounting; requires database access, never a public endpoint."""

import argparse
import asyncio
from datetime import UTC, datetime

from nevo.core.config import get_settings
from nevo.db.session import create_engine
from nevo.ops.media_usage import json_report, report


async def main(since, until):
    engine = create_engine(get_settings().database_url)
    try:
        print(json_report(await report(engine, since, until)))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="since", required=True, type=datetime.fromisoformat)
    parser.add_argument("--until", type=datetime.fromisoformat, default=datetime.now(UTC))
    args = parser.parse_args()
    if args.since.tzinfo is None or args.until.tzinfo is None or args.since >= args.until:
        parser.error("Supply an increasing range with timezone offsets")
    asyncio.run(main(args.since, args.until))
