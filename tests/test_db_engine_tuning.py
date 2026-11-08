"""The engine has to assume the database is a network hop away.

Every avoidable round trip here is latency on every request, so these pin the
choices that were costing one.
"""

from nevo.db.session import _is_transaction_pooler, create_engine, statement_cache_size

SESSION_URL = "postgresql+asyncpg://u:p@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"
TRANSACTION_URL = "postgresql+asyncpg://u:p@aws-0-eu-west-1.pooler.supabase.com:6543/postgres"


def test_session_mode_is_not_mistaken_for_transaction_mode() -> None:
    assert not _is_transaction_pooler(SESSION_URL)
    assert _is_transaction_pooler(TRANSACTION_URL)


def test_session_pooling_keeps_the_statement_cache() -> None:
    """Without it every query is parsed and planned again.

    Measured at roughly 40% of query time against a remote database: cache off
    is two round trips, cache on is one.
    """
    assert statement_cache_size(SESSION_URL) == 256


def test_transaction_pooling_still_disables_the_statement_cache() -> None:
    """Each query may land on a different backend, so a cached statement
    collides with one another logical connection already prepared."""
    assert statement_cache_size(TRANSACTION_URL) == 0


def test_every_checkout_is_pre_pinged() -> None:
    """A dead connection must not reach a request.

    This pinned pre_ping off, on the reasoning that recycling under the
    pooler's idle timeout kept connections fresh for less cost than a round
    trip per checkout. True of the session pooler, where a checkout is a
    stable session and age is a fair proxy for liveness.

    It stopped being true when the service moved to the transaction pooler,
    which may drop a client connection between transactions whatever its
    age. The port moved and this assumption did not, so a connection the
    pooler had already closed was handed to a request and failed on first
    use - DBAPIError, intermittently, on a service that was up.

    Recycling is kept as well. Pre-ping replaces a dead connection;
    recycling stops one being held long enough to be dropped. They were
    read as alternatives and they are not.
    """
    engine = create_engine(SESSION_URL)

    assert engine.pool._pre_ping is True  # type: ignore[attr-defined]
    assert engine.pool._recycle == 280  # type: ignore[attr-defined]


def test_connections_are_held_open_because_the_handshake_is_costly() -> None:
    """The connect handshake measured far longer than a query, so reopening
    per request would dominate.

    How many to hold depends on which pooler. The session pooler has a
    fifteen-client project limit shared across services, so one process is
    capped at two plus one overflow rather than taking most of it. The
    transaction pooler multiplexes and has no such ceiling, so the
    configured size stands.

    This asserted ten against the session URL, which the cap had already
    made two - stale since the cap landed, and worth keeping because the
    difference between the two poolers is exactly what caught us out.
    """
    assert create_engine(SESSION_URL).pool.size() == 2
    assert create_engine(TRANSACTION_URL).pool.size() == 10


def test_transaction_pooler_disables_both_caches_and_uses_unique_statement_names(monkeypatch):
    captured = {}

    def factory(url, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("nevo.db.session.create_async_engine", factory)
    create_engine(TRANSACTION_URL)
    assert captured["pool_size"] == 10
    assert captured["max_overflow"] == 10
    args = captured["connect_args"]
    assert args["statement_cache_size"] == args["prepared_statement_cache_size"] == 0
    assert args["prepared_statement_name_func"]() != args["prepared_statement_name_func"]()


def test_transaction_pooler_reuses_client_connections():
    engine = create_engine(TRANSACTION_URL)
    assert engine.pool.size() == 10
