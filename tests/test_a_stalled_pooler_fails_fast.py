"""A pooler that accepts a connection and stalls must not hang a request.

8 November. Supavisor answered ECHECKOUTTIMEOUT after its own sixty-second
wait for a backend, so every database request hung for sixty-one seconds
before failing. Each one held a worker for a full minute to learn nothing,
and enough piled up that /openapi.json - which touches no database - went
slow too.

A connect timeout does not bound this. Supavisor accepts the connection and
authenticates it before stalling, so the driver believes it is connected.
Measured against production while it was failing: a twenty-second connect
timeout still took sixty-two seconds, while an eight-second command timeout
failed in twelve.

Neither setting makes a struggling pooler work. They are the difference
between requests that fail and a service that stops answering.
"""

from __future__ import annotations

import inspect

from nevo.db import session as session_module
from nevo.db.session import (
    COMMAND_TIMEOUT_SECONDS,
    CONNECT_TIMEOUT_SECONDS,
    create_engine,
)

TRANSACTION_URL = "postgresql+asyncpg://u:p@aws-0-eu-west-1.pooler.supabase.com:6543/postgres"
SESSION_URL = "postgresql+asyncpg://u:p@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"


def _connect_args(url: str, monkeypatch) -> dict:
    captured: dict = {}

    def factory(_url, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("nevo.db.session.create_async_engine", factory)
    create_engine(url)
    return captured["connect_args"]


def test_both_timeouts_are_set_on_every_pooler(monkeypatch) -> None:
    for url in (TRANSACTION_URL, SESSION_URL):
        args = _connect_args(url, monkeypatch)
        assert args["timeout"] == CONNECT_TIMEOUT_SECONDS, url
        assert args["command_timeout"] == COMMAND_TIMEOUT_SECONDS, url


def test_the_command_timeout_bounds_the_observed_failure() -> None:
    # Sixty-one seconds was the thing to stop. Anything at or above the
    # pooler's own sixty-second wait bounds nothing.
    assert COMMAND_TIMEOUT_SECONDS < 60


def test_it_leaves_room_for_the_background_sweeps() -> None:
    # The retention and billing passes share this engine, and a pass over a
    # large table is legitimately slow. A deadline tight enough to feel
    # responsive would fail honest work instead.
    assert COMMAND_TIMEOUT_SECONDS >= 30


def test_the_connect_timeout_is_kept_for_an_unreachable_host() -> None:
    # It does not bound a pooler that accepts and stalls, which is why it
    # was not enough on its own, but it is what catches a host that never
    # answers at all.
    assert CONNECT_TIMEOUT_SECONDS < COMMAND_TIMEOUT_SECONDS
    source = inspect.getsource(session_module.create_engine)
    assert "command_timeout" in source
