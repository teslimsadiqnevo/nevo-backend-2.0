from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

TRANSACTION_POOLER_PORT = 6543
"""Supabase serves transaction-mode pooling here and session mode on 5432."""


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
    return f":{TRANSACTION_POOLER_PORT}/" in database_url


def create_engine(database_url: str) -> AsyncEngine:
    """Engine tuned for a database that is a network hop away.

    Against a remote database every avoidable round trip is real latency on
    every request, so the defaults here trade a little safety margin for not
    paying that repeatedly.
    """
    return create_async_engine(
        database_url,
        # A pre-ping is a full round trip before the request's first real
        # query. That is cheap against a local database and expensive against
        # a remote one. Recycling below the pooler's idle timeout keeps
        # connections fresh instead, without paying per checkout.
        pool_pre_ping=False,
        pool_recycle=280,
        # Connections are expensive to establish here - the handshake costs
        # far more than a query - so hold a few open rather than reopening.
        pool_size=10,
        max_overflow=10,
        pool_timeout=10,
        connect_args={
            "statement_cache_size": statement_cache_size(database_url),
        },
    )


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )
