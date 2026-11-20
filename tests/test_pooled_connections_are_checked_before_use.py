"""A connection the pooler has already dropped must not reach a request.

Production, 7 November. The service was awake - /openapi.json answered in
1.4s while database routes hung - and /health came back with
schemaError "DBAPIError" at 18:41, 18:55, 19:34, 20:27 and 20:30.

pool_pre_ping was off, on the reasoning that recycling under the pooler's
idle timeout keeps connections fresh for less cost than a round trip per
checkout. That reasoning holds for the session pooler, where a checkout is
a stable session and age is a fair proxy for liveness. It does not hold for
the transaction pooler, which may drop a client connection between
transactions whatever its age.

The port moved and the assumption did not, so a dead connection was handed
to a request and failed on first use.

20 November: the database moved again, to Render's own Postgres, and this
test's own premise - "the cost of being right is a few milliseconds" -
stopped being true with it. A round trip to Frankfurt from the US dyno
measures ~185ms, so a pre-ping is ~185ms on the first query of every
checkout. Measured on the dyno the same day: Render's idle_session_timeout
is 0, so the server never closes an idle session, tcp_keepalives_idle is
300, and a pooled connection was reused fine after 120s, 300s and 600s
idle. There is no dropped connection there to catch.

So the guard keeps its full force where the failure happens - both
Supabase poolers, which the London project still is while it remains the
rollback - and a direct Postgres stops paying for it. That is now asserted
in both directions, so neither half can be dropped by accident.
"""

from __future__ import annotations

import inspect

from nevo.db import session as session_module
from nevo.db.session import create_engine

SESSION_POOLER = "postgresql+asyncpg://u:p@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"
TRANSACTION_POOLER = "postgresql+asyncpg://u:p@aws-0-eu-west-1.pooler.supabase.com:6543/postgres"
LOCAL = "postgresql+asyncpg://u:p@localhost:5432/nevo"


RENDER = "postgresql+asyncpg://u:p@dpg-x-a.frankfurt-postgres.render.com:5432/nevo"


def test_every_pooled_checkout_is_validated() -> None:
    # Whichever pooler, because the cost of being wrong is a failed request.
    # This is the 7 November failure and it is not negotiable.
    for url in (SESSION_POOLER, TRANSACTION_POOLER):
        assert create_engine(url).pool._pre_ping is True, url


def test_a_direct_postgres_is_not_pinged() -> None:
    # ~185ms per checkout against a database an ocean away, to catch a
    # dropped connection that a direct Postgres does not drop. Asserted
    # rather than merely allowed, so restoring the ping here has to be a
    # decision somebody writes down.
    for url in (RENDER, LOCAL):
        assert create_engine(url).pool._pre_ping is False, url


def test_recycling_is_kept_as_well() -> None:
    # Pre-ping replaces a dead connection; recycling still stops one being
    # held long enough to be dropped in the first place. They are not
    # alternatives, which is how this was read before.
    source = inspect.getsource(session_module.create_engine)
    assert "pool_recycle=280" in source


def test_the_transaction_pooler_still_drops_prepared_statements() -> None:
    # The other thing transaction mode breaks, and the one that was handled.
    from nevo.db.session import statement_cache_size

    assert statement_cache_size(TRANSACTION_POOLER) == 0
    assert statement_cache_size(SESSION_POOLER) > 0
