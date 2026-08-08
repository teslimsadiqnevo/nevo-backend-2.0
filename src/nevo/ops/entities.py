from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class HeartbeatRecord:
    id: UUID
    beat_date: date
    created_at: datetime
