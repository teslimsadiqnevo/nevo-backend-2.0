from typing import Annotated, Any, TypeVar

from fastapi import Query, Response
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

LimitQuery = Annotated[int, Query(ge=1, le=MAX_LIMIT, alias="limit")]
OffsetQuery = Annotated[int, Query(ge=0, alias="offset")]

TOTAL_HEADER = "X-Total-Count"
HAS_MORE_HEADER = "X-Has-More"

T = TypeVar("T")


async def paginate(
    session: AsyncSession,
    query: Select[Any],
    *,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> tuple[list[Any], int]:
    """Return one page of a query plus the unpaged total.

    The total is what makes truncation visible: without it a client cannot
    tell a complete list from a capped one, which is how rows go missing
    silently rather than loudly.
    """
    total = await session.scalar(
        select(func.count()).select_from(query.order_by(None).subquery())
    )
    rows = (await session.scalars(query.limit(limit).offset(offset))).all()
    return list(rows), int(total or 0)


def set_page_headers(
    response: Response,
    *,
    total: int,
    limit: int,
    offset: int,
) -> None:
    """Report the total and whether more remains, for array-shaped responses.

    These endpoints return a bare JSON array, so there is nowhere in the body
    to put a total without breaking existing clients. Headers carry it instead.
    """
    response.headers[TOTAL_HEADER] = str(total)
    response.headers[HAS_MORE_HEADER] = "true" if offset + limit < total else "false"


def has_more(*, total: int, limit: int, offset: int) -> bool:
    return offset + limit < total
