"""The background process: everything that polls, and nothing that serves.

Started as the `worker` dyno. It builds the application exactly as the API
dyno does - same lifespan, same wiring - and then simply waits, because the
work is in the poll loops the lifespan starts. Sharing the lifespan rather
than writing a second wiring path is deliberate: two paths drift, and the
one that drifts is the one nobody looks at.

Which process owns the loops is decided in one place,
``Settings.run_background_workers``, from the platform's own ``DYNO``. So
this module does not pass a flag or set an environment variable; it is the
worker because the platform called it one.

Why it exists at all: the API serves from a single uvicorn process, so there
is one event loop. Fifteen poll loops sharing that loop and the connection
pool with real requests is what took the service from 1.5s to 16s on
19 November.
"""

from __future__ import annotations

import asyncio
import logging
import signal

logger = logging.getLogger(__name__)


async def run() -> None:
    """Hold the application open until the platform asks us to stop."""
    # Imported here, not at module scope: importing the app builds every
    # router, and a failure doing that should be reported by this function
    # rather than at import time, where it has no log context.
    from nevo.main import app, lifespan

    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        # Heroku sends SIGTERM and gives us 30 seconds. Catching it means the
        # lifespan's teardown runs - workers stop, leases are released, the
        # engine is disposed - instead of the process being killed mid-task
        # and leaving a row leased to nobody until its lease expires.
        loop.add_signal_handler(sig, stopping.set)

    async with lifespan(app):
        logger.info("Background worker process started; waiting for work.")
        await stopping.wait()
        logger.info("Stop requested; shutting the workers down.")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())


if __name__ == "__main__":
    main()
