"""Work that outlives the request that asked for it.

Parsing a lesson takes minutes of model calls, image generation and speech
synthesis. Done inside the request, every proxy between here and the browser
hangs up first - and a hang-up on work that is still running looks exactly
like a backend that never answers.
"""
import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

_running: set[asyncio.Task[None]] = set()


def spawn(work: Callable[[], Awaitable[None]], *, name: str) -> asyncio.Task[None]:
    """Run ``work`` after the response has gone, and keep a reference.

    asyncio holds only a weak reference to a bare task, so one that nobody
    keeps can be collected mid-flight. The set is what stops that.
    """

    async def guarded() -> None:
        try:
            await work()
        except Exception:
            # The caller has already been answered, so the only place this can
            # be reported is the log and whatever record the work updates.
            logger.exception("Background task %s failed", name)

    task = asyncio.create_task(guarded(), name=name)
    _running.add(task)
    task.add_done_callback(_running.discard)
    return task


def in_flight() -> int:
    return len(_running)
