from uuid import uuid4

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from nevo.core.config import get_settings

TRANSACTION_POOLER_PORT = 6543
"""Supabase serves transaction-mode pooling here and session mode on 5432."""
SESSION_POOLER_PORT = 5432


def statement_cache_size(database_url: str) -> int:
    """How many prepared statements asyncpg may cache on a connection.

    Zero through a transaction-mode pooler, where each query may land on a
    different backend and a cached statement collides with one another
    logical connection already prepared. Otherwise the connection is ours for
    its lifetime and caching is worth having: without it every query is parsed
    and planned again, which measured at roughly 40% of query time against a
    remote database.
    """
    return 0 if _is_transaction_pooler(database_url) else 256


def _is_transaction_pooler(database_url: str) -> bool:
    """Whether each query may land on a different backend connection.

    Only true for the transaction-mode pooler. Getting this wrong in one
    direction breaks prepared statements; in the other it throws away the
    statement cache for nothing.
    """
    return make_url(database_url).port == TRANSACTION_POOLER_PORT


def _is_supabase_session_pooler(database_url: str) -> bool:
    url = make_url(database_url)
    return bool(url.host and url.host.endswith(".pooler.supabase.com") and url.port == SESSION_POOLER_PORT)


def create_engine(database_url: str) -> AsyncEngine:
    """Engine tuned for a database that is a network hop away.

    Against a remote database every avoidable round trip is real latency on
    every request, so the defaults here trade a little safety margin for not
    paying that repeatedly.
    """
    settings = get_settings()
    session_pooler = _is_supabase_session_pooler(database_url)
    connect_args = {"statement_cache_size": statement_cache_size(database_url)}
    if _is_transaction_pooler(database_url):
        # Reuse client connections without reusing another transaction's prepared statements.
        connect_args.update(
            prepared_statement_cache_size=0,
            prepared_statement_name_func=lambda: f"__nevo_{uuid4().hex}__",
        )
    return create_async_engine(
        database_url,
        # A pre-ping is a full round trip before the request's first real
        # query, and this used to be off: recycling under the pooler's idle
        # timeout was treated as keeping connections fresh for less cost.
        #
        # That held for the session pooler, where a checkout is a stable
        # session and an age limit is a fair proxy for liveness. It does not
        # hold for the transaction pooler, which may drop a client
        # connection between transactions whatever its age - so a dead
        # connection was handed to a request and failed on first use, as a
        # DBAPIError, intermittently, on a service that was up. Observed in
        # production on 7 November at 18:41, 18:55, 19:34, 20:27 and 20:30.
        #
        # The assumption moved with the port and the setting did not. One
        # round trip per checkout is a few milliseconds against a database
        # this far away, and it is the difference between a stale connection
        # being replaced and a request failing.
        pool_pre_ping=True,
        pool_recycle=280,
        # Connections are expensive to establish here - the handshake costs
        # far more than a query - so hold a few open rather than reopening.
        # The Supabase session pooler has a 15-client project limit. Multiple
        # services share it, so never let one process reserve most of it.
        pool_size=min(settings.database_pool_size, 2) if session_pooler else settings.database_pool_size,
        max_overflow=min(settings.database_max_overflow, 1) if session_pooler else settings.database_max_overflow,
        pool_timeout=10,
        connect_args=connect_args,
    )


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )
