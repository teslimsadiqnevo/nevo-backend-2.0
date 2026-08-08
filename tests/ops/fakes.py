from datetime import UTC, date, datetime
from uuid import uuid4

from nevo.ops.entities import HeartbeatRecord


class MemoryHeartbeatRepository:
    def __init__(self) -> None:
        self.calls: list[date] = []
        self.written_dates: set[date] = set()

    async def record(self, beat_date: date) -> HeartbeatRecord | None:
        self.calls.append(beat_date)
        if beat_date in self.written_dates:
            return None
        self.written_dates.add(beat_date)
        return HeartbeatRecord(
            id=uuid4(),
            beat_date=beat_date,
            created_at=datetime.now(UTC),
        )
