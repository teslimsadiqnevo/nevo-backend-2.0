import asyncio
from datetime import date

from nevo.ops.heartbeat import HeartbeatLoop

from .fakes import MemoryHeartbeatRepository


async def test_heartbeat_loop_writes_immediately_and_repeatedly() -> None:
    repository = MemoryHeartbeatRepository()
    loop = HeartbeatLoop(
        repository=repository,
        check_interval_seconds=0.01,
        today=lambda: date(2026, 8, 8),
    )

    loop.start()
    for _ in range(50):
        if len(repository.calls) >= 3:
            break
        await asyncio.sleep(0.01)
    await loop.stop()

    assert len(repository.calls) >= 3
    assert all(call == date(2026, 8, 8) for call in repository.calls)
    assert repository.written_dates == {date(2026, 8, 8)}


async def test_heartbeat_loop_is_idempotent_within_a_day() -> None:
    repository = MemoryHeartbeatRepository()
    loop = HeartbeatLoop(
        repository=repository,
        check_interval_seconds=0.01,
        today=lambda: date(2026, 8, 8),
    )

    loop.start()
    await asyncio.sleep(0.05)
    await loop.stop()

    assert len(repository.written_dates) == 1


async def test_heartbeat_loop_start_is_idempotent() -> None:
    repository = MemoryHeartbeatRepository()
    loop = HeartbeatLoop(
        repository=repository,
        check_interval_seconds=10,
        today=lambda: date(2026, 8, 8),
    )

    loop.start()
    first_task = loop._task
    loop.start()

    assert loop._task is first_task
    await loop.stop()


async def test_heartbeat_loop_stop_without_start_is_safe() -> None:
    loop = HeartbeatLoop(
        repository=MemoryHeartbeatRepository(),
        check_interval_seconds=10,
    )

    await loop.stop()
