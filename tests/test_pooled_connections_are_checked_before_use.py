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
"""

from __future__ import annotations

import inspect

from nevo.db import session as session_module
from nevo.db.session import create_engine

SESSION_POOLER = "postgresql+asyncpg://u:p@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"
TRANSACTION_POOLER = "postgresql+asyncpg://u:p@aws-0-eu-west-1.pooler.supabase.com:6543/postgres"
LOCAL = "postgresql+asyncpg://u:p@localhost:5432/nevo"


def test_every_checkout_is_validated() -> None:
    # Whichever pooler, because the cost of being wrong is a failed request
    # and the cost of being right is a few milliseconds.
    for url in (SESSION_POOLER, TRANSACTION_POOLER, LOCAL):
        assert create_engine(url).pool._pre_ping is True, url


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
