import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from itertools import count

from nevo.ai_gateway.entities import ProviderResponse
from nevo.ai_gateway.errors import SchedulerClosedError
from nevo.ai_gateway.ports import ProviderOperation
from nevo.domain.ai_gateway.vocabulary import AiPriority


@dataclass(order=True, slots=True)
class _ScheduledRequest:
    priority: int
    sequence: int
    operation: ProviderOperation = field(compare=False)
    future: asyncio.Future[ProviderResponse] = field(compare=False)


class PriorityRateLimitedScheduler:
    def __init__(
        self,
        *,
        max_concurrency: int,
        requests_per_minute: int,
    ) -> None:
        self._max_concurrency = max_concurrency
        self._requests_per_minute = requests_per_minute
        self._queue: asyncio.PriorityQueue[_ScheduledRequest] = (
            asyncio.PriorityQueue()
        )
        self._sequence = count()
        self._workers: list[asyncio.Task[None]] = []
        self._start_lock = asyncio.Lock()
        self._rate_lock = asyncio.Lock()
        self._request_times: deque[float] = deque()
        self._closed = False

    async def execute(
        self,
        priority: AiPriority,
        operation: ProviderOperation,
    ) -> ProviderResponse:
        if self._closed:
            raise SchedulerClosedError
        await self._ensure_workers()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[ProviderResponse] = loop.create_future()
        await self._queue.put(
            _ScheduledRequest(
                priority=int(priority),
                sequence=next(self._sequence),
                operation=operation,
                future=future,
            )
        )
        return await future

    async def close(self) -> None:
        self._closed = True
        if not self._workers:
            return
        await self._queue.join()
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def _ensure_workers(self) -> None:
        if self._workers:
            return
        async with self._start_lock:
            if self._workers:
                return
            self._workers = [
                asyncio.create_task(
                    self._worker(),
                    name=f"ai-gateway-worker-{index}",
                )
                for index in range(self._max_concurrency)
            ]

    async def _worker(self) -> None:
        while True:
            scheduled = await self._queue.get()
            try:
                await self._await_rate_slot()
                response = await scheduled.operation()
            except asyncio.CancelledError:
                if not scheduled.future.done():
                    scheduled.future.cancel()
                raise
            except Exception as error:
                if not scheduled.future.done():
                    scheduled.future.set_exception(error)
            else:
                if not scheduled.future.done():
                    scheduled.future.set_result(response)
            finally:
                self._queue.task_done()

    async def _await_rate_slot(self) -> None:
        window_seconds = 60.0
        while True:
            async with self._rate_lock:
                now = time.monotonic()
                while (
                    self._request_times
                    and now - self._request_times[0] >= window_seconds
                ):
                    self._request_times.popleft()
                if len(self._request_times) < self._requests_per_minute:
                    self._request_times.append(now)
                    return
                wait_seconds = window_seconds - (
                    now - self._request_times[0]
                )
            await asyncio.sleep(max(wait_seconds, 0.001))
