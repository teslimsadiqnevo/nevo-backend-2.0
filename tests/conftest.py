"""Provider unit tests must never write accounting to the developer's database."""

from uuid import uuid4

import pytest


class MemoryMediaLedger:
    def __init__(self):
        self.rows = {}

    async def start(self, values):
        event_id = uuid4()
        self.rows[event_id] = {"id": event_id, "status": "started", **values}
        return event_id

    async def finish(self, event_id, **values):
        self.rows[event_id].update(values)


@pytest.fixture(autouse=True)
def media_ledger(monkeypatch):
    from nevo.ops import media_usage

    ledger = MemoryMediaLedger()
    monkeypatch.setattr(media_usage, "default_ledger", lambda: ledger)
    monkeypatch.setenv("MEDIA_PRICING_JSON", "{}")
    return ledger
