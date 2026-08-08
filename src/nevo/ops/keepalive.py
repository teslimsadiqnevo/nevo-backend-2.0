import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)


class SelfPingLoop:
    """Periodically requests the app's own public health endpoint.

    Host idle timers reset on inbound HTTP traffic. A process pinging
    itself over loopback would not register as that traffic, so this
    calls out to the public URL instead, producing a genuine external
    request back to the same instance.
    """

    def __init__(
        self,
        *,
        health_url: str | None,
        interval_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._health_url = health_url
        self._interval_seconds = interval_seconds
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(10.0)
        )
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if not self._health_url or self._task is not None:
            return
        self._task = asyncio.create_task(
            self._run(),
            name="self-ping-loop",
        )

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        await self._client.aclose()

    async def _run(self) -> None:
        assert self._health_url is not None
        while True:
            try:
                await self._client.get(self._health_url)
            except asyncio.CancelledError:
                raise
            except httpx.HTTPError:
                logger.warning("Self-ping request failed", exc_info=True)
            await asyncio.sleep(self._interval_seconds)
