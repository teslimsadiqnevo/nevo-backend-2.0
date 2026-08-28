from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    sessions = getattr(request.app.state, "db_sessions", None)
    if sessions is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "database_unavailable",
                "message": "Database access is temporarily unavailable.",
            },
        )
    return sessions


async def database_session(
    sessions: Annotated[
        async_sessionmaker[AsyncSession],
        Depends(get_session_factory),
    ],
) -> AsyncIterator[AsyncSession]:
    async with sessions() as session:
        yield session


DatabaseSession = Annotated[AsyncSession, Depends(database_session)]
