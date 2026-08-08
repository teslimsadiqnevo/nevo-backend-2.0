from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(
        database_url,
        pool_pre_ping=True,
        # Poolers such as Supabase's PgBouncer (transaction mode) route each
        # query to a different backend connection, so asyncpg's server-side
        # prepared statement cache collides with statements another logical
        # connection already prepared on the same backend. Disabling it
        # trades a small per-query overhead for correctness through a
        # pooler; it is a no-op against a direct, unpooled connection.
        connect_args={"statement_cache_size": 0},
    )


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )
