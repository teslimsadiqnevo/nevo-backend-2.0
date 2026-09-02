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


def test_no_pre_ping_round_trip_before_every_request() -> None:
    """A pre-ping is a full round trip before the first real query. Cheap
    locally, expensive remotely; connections are recycled instead."""
    engine = create_engine(SESSION_URL)

    assert engine.pool._pre_ping is False  # type: ignore[attr-defined]
    assert engine.pool._recycle == 280  # type: ignore[attr-defined]


def test_connections_are_held_open_because_the_handshake_is_costly() -> None:
    """The connect handshake measured far longer than a query, so reopening
    per request would dominate."""
    engine = create_engine(SESSION_URL)

    assert engine.pool.size() == 10
