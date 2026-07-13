from typing import Protocol

from nevo.signal_events.entities import SignalIngestionBatch


class SignalIngestionRepository(Protocol):
    async def ingest(self, batch: SignalIngestionBatch) -> None:
        """Persist one lesson session snapshot and its signal events."""

