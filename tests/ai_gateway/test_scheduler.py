import asyncio

from nevo.ai_gateway.entities import ProviderResponse
from nevo.ai_gateway.scheduler import PriorityRateLimitedScheduler
from nevo.domain.ai_gateway.vocabulary import AiPriority, AiProviderName


def response(text: str) -> ProviderResponse:
    return ProviderResponse(
        text=text,
        provider=AiProviderName.GEMINI,
        model="test",
    )


async def test_waiting_requests_are_dispatched_by_priority() -> None:
    scheduler = PriorityRateLimitedScheduler(
        max_concurrency=1,
        requests_per_minute=100,
    )
    started = asyncio.Event()
    release = asyncio.Event()
    order: list[str] = []

    async def blocking() -> ProviderResponse:
        order.append("blocking")
        started.set()
        await release.wait()
        return response("blocking")

    async def low_priority() -> ProviderResponse:
        order.append("low")
        return response("low")

    async def high_priority() -> ProviderResponse:
        order.append("high")
        return response("high")

    first = asyncio.create_task(
        scheduler.execute(AiPriority.LESSON_GENERATION, blocking)
    )
    await started.wait()
    low = asyncio.create_task(
        scheduler.execute(AiPriority.NARRATIVE, low_priority)
    )
    high = asyncio.create_task(
        scheduler.execute(AiPriority.ADAPTATION, high_priority)
    )
    await asyncio.sleep(0)
    release.set()

    await asyncio.gather(first, low, high)
    await scheduler.close()

    assert order == ["blocking", "high", "low"]
