"""Parent sign-in codes against real Postgres, inside a rolled-back txn.

A four-digit code is ten thousand combinations. What makes that safe is the
controls around it, so these are the tests that matter.
"""
import os
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from nevo.auth.parent_codes import MAX_ATTEMPTS, ParentLoginCodes
from nevo.core.config import get_settings
from nevo.db.models.auth import ParentLoginCode
from nevo.db.session import create_engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL"),
        reason="TEST_DATABASE_URL is required for PostgreSQL integration tests",
    ),
]

CONTACT = "ada.okoro@example.com"


async def in_rollback(check):  # type: ignore[no-untyped-def]
    engine = create_engine(get_settings().database_url)
    connection = await engine.connect()
    transaction = await connection.begin()
    try:
        sessions = async_sessionmaker(bind=connection, expire_on_commit=False)
        return await check(ParentLoginCodes(sessions, pepper="test-pepper"), sessions)
    finally:
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


async def test_a_code_signs_a_parent_in_once_and_only_once() -> None:
    parent_id = uuid.uuid4()

    async def check(codes, sessions):  # type: ignore[no-untyped-def]
        issued = await codes.issue(contact=CONTACT, parent_user_id=None)
        first = await codes.redeem(contact=CONTACT, code=issued.code)
        second = await codes.redeem(contact=CONTACT, code=issued.code)
        return issued, first, second

    issued, first, second = await in_rollback(check)

    assert issued.code is not None and issued.code.isdigit()
    assert len(issued.code) == 4
    # parent_user_id was None, so redeeming returns None but still consumes.
    assert first is None
    assert second is None
    del parent_id


async def test_the_code_is_never_stored_in_the_clear() -> None:
    """The table would otherwise be a list of live credentials."""

    async def check(codes, sessions):  # type: ignore[no-untyped-def]
        issued = await codes.issue(contact=CONTACT, parent_user_id=None)
        async with sessions() as session:
            stored = list(await session.scalars(select(ParentLoginCode.code_digest)))
        return issued.code, stored

    code, stored = await in_rollback(check)

    assert stored
    assert code not in stored
    assert all(len(digest) == 64 for digest in stored)


async def test_a_code_dies_after_a_handful_of_wrong_guesses() -> None:
    """Without this, ten thousand combinations is an afternoon's work."""

    async def check(codes, sessions):  # type: ignore[no-untyped-def]
        issued = await codes.issue(contact=CONTACT, parent_user_id=None)
        wrong = "0000" if issued.code != "0000" else "1111"
        for _ in range(MAX_ATTEMPTS + 1):
            await codes.redeem(contact=CONTACT, code=wrong)
        async with sessions() as session:
            record = (
                await session.scalars(
                    select(ParentLoginCode).where(ParentLoginCode.contact == CONTACT)
                )
            ).first()
        return record.consumed_at

    consumed_at = await in_rollback(check)

    assert consumed_at is not None


async def test_asking_for_a_new_code_kills_the_old_one() -> None:
    """Otherwise an attacker collects live codes and guesses one each."""

    async def check(codes, sessions):  # type: ignore[no-untyped-def]
        first = await codes.issue(contact=CONTACT, parent_user_id=None)
        await codes.issue(contact=CONTACT, parent_user_id=None)
        return await codes.redeem(contact=CONTACT, code=first.code)

    assert await in_rollback(check) is None


async def test_a_flood_of_requests_stops_producing_codes() -> None:
    """The attempt cap is worthless if new codes are free."""

    async def check(codes, sessions):  # type: ignore[no-untyped-def]
        return [
            (await codes.issue(contact=CONTACT, parent_user_id=None)).code
            for _ in range(8)
        ]

    produced = await in_rollback(check)

    assert produced.count(None) > 0
    # And it still reports an expiry, so the caller cannot tell throttling
    # apart from an ordinary send.
    assert produced[0] is not None


async def test_a_digest_cannot_be_replayed_against_another_parent() -> None:
    """The digest is bound to the contact it was minted for."""

    async def check(codes, sessions):  # type: ignore[no-untyped-def]
        issued = await codes.issue(contact=CONTACT, parent_user_id=None)
        return (
            codes.digest(CONTACT, issued.code),
            codes.digest("someone.else@example.com", issued.code),
        )

    mine, theirs = await in_rollback(check)

    assert mine != theirs
