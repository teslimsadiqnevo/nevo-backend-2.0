from datetime import date
from typing import Protocol

from nevo.ops.entities import HeartbeatRecord


class HeartbeatRepository(Protocol):
    async def record(self, beat_date: date) -> HeartbeatRecord | None: ...
