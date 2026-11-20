"""The pooler's settings belong to the pooler, not to every database.

Two settings were added on 7 November because Supabase's transaction pooler
dropped client connections between transactions, handing a dead one to a
request: a pre-ping on every checkout, and an age limit under the pooler's
idle timeout. They were right for that database and they moved with us to
Render, where they are not right at all.

Measured on the dyno, 20 November: Render's idle_session_timeout is 0, so
the server never closes an idle session, tcp_keepalives_idle is 300, and a
pooled connection was reused fine after 120s, 300s and 600s idle. A round
trip to Frankfurt from the US dyno is ~185ms, so the pre-ping was adding
~185ms to the first query of every checkout to guard against a failure that
cannot happen there.

These tests keep both halves true at once, because the pooler settings must
survive for anything still pointed at Supabase - the London project is the
rollback.
"""

from __future__ import annotations

import pytest

from nevo.db.session import create_engine

RENDER = "postgresql+asyncpg://u:p@dpg-x-a.frankfurt-postgres.render.com:5432/nevo"
SUPABASE_TRANSACTION = "postgresql+asyncpg://u:p@aws-0-eu-west-2.pooler.supabase.com:6543/postgres"
SUPABASE_SESSION = "postgresql+asyncpg://u:p@aws-0-eu-west-2.pooler.supabase.com:5432/postgres"
LOCAL = "postgresql+asyncpg://u:p@localhost:5432/nevo"


@pytest.mark.parametrize("url", [RENDER, LOCAL])
def test_a_direct_postgres_pays_for_no_pre_ping(url: str) -> None:
    """~185ms per checkout, for a stale connection that never arrives."""
    pool = create_engine(url).pool
    assert pool._pre_ping is False


@pytest.mark.parametrize("url", [RENDER, LOCAL])
def test_a_direct_postgres_is_not_recycled_every_280_seconds(url: str) -> None:
    """280s was Supabase's idle window. Here it is only churn - and each new
    connection is a TLS and auth handshake across the Atlantic."""
    pool = create_engine(url).pool
    assert pool._recycle >= 1800


@pytest.mark.parametrize("url", [SUPABASE_TRANSACTION, SUPABASE_SESSION])
def test_a_pooler_keeps_both_guards(url: str) -> None:
    """The 7 November failures were real. Nothing here may undo that."""
    pool = create_engine(url).pool
    assert pool._pre_ping is True
    assert pool._recycle == 280


def test_only_the_session_pooler_clamps_the_pool() -> None:
    """Supabase's session pooler has a project-wide client limit; Render
    does not, and clamping to 2 against Render is what exhausted the pool on
    19 November."""
    assert create_engine(SUPABASE_SESSION).pool.size() == 2
    assert create_engine(RENDER).pool.size() > 2
