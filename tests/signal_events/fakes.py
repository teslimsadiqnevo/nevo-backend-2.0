from nevo.signal_events.entities import SignalIngestionBatch


class MemorySignalIngestionRepository:
    def __init__(self) -> None:
        self.batches: list[SignalIngestionBatch] = []

    async def ingest(self, batch: SignalIngestionBatch) -> None:
        self.batches.append(batch)

