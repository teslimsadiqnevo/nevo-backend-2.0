from nevo.signal_events.entities import (
    SignalIngestionBatch,
    SignalIngestionReceipt,
)
from nevo.signal_events.errors import (
    EmptySignalBatchError,
    SessionMismatchError,
    SignalBatchTooLargeError,
)
from nevo.signal_events.ports import SignalIngestionRepository

MAX_SIGNAL_BATCH_SIZE = 100


class SignalIngestionService:
    def __init__(self, repository: SignalIngestionRepository) -> None:
        self._repository = repository

    async def ingest(
        self,
        batch: SignalIngestionBatch,
    ) -> SignalIngestionReceipt:
        if not batch.events:
            raise EmptySignalBatchError
        if len(batch.events) > MAX_SIGNAL_BATCH_SIZE:
            raise SignalBatchTooLargeError
        if any(event.session_id != batch.session.id for event in batch.events):
            raise SessionMismatchError

        await self._repository.ingest(batch)
        return SignalIngestionReceipt(
            session_id=batch.session.id,
            accepted_events=len(batch.events),
        )

