"""/health says which database the process is using, and nothing secret.

Yinka, 10 November: the one thing that would have settled a day of guessing.
The code pins a production project ref and render.yaml declares it, but
DATABASE_URL is set by hand per environment, so what a running service had
actually connected to was unknowable from outside without the dashboard.

Host, project ref and region. No user, no password, no database name.
"""

from __future__ import annotations

import pytest

from nevo.core.config import Settings

POOLED = (
    "postgresql+asyncpg://postgres.ibavgeinubvmktxufvvr:s3cret"
    "@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"
)
DIRECT = "postgresql+asyncpg://postgres:s3cret@db.ibavgeinubvmktxufvvr.supabase.co:5432/postgres"
LOCAL = "postgresql+asyncpg://postgres:postgres@localhost:5432/nevo"


def _identity(url: str) -> dict[str, str]:
    return Settings(DATABASE_URL=url).database_identity


def test_the_pooled_production_url_is_named_in_full() -> None:
    found = _identity(POOLED)
    assert found["projectRef"] == "ibavgeinubvmktxufvvr"
    assert found["region"] == "eu-west-1"
    assert found["host"] == "aws-0-eu-west-1.pooler.supabase.com"
    assert found["port"] == "5432"
    assert found["isPinnedProductionProject"] == "true"


def test_a_direct_connection_is_recognised_too() -> None:
    """Not every environment goes through the pooler."""
    assert _identity(DIRECT)["projectRef"] == "ibavgeinubvmktxufvvr"
    assert _identity(DIRECT)["isPinnedProductionProject"] == "true"


def test_a_different_project_is_not_claimed_to_be_production() -> None:
    """The whole point: telling the migrated project from any other one."""
    other = POOLED.replace("ibavgeinubvmktxufvvr", "someotherprojectref00")
    found = _identity(other)
    assert found["projectRef"] == "someotherprojectref00"
    assert found["isPinnedProductionProject"] == "false"


def test_a_local_database_names_no_project(monkeypatch) -> None:
    monkeypatch.setenv("NEVO_ALLOW_DATABASE_TARGET", "1")
    found = _identity(LOCAL)
    assert found["host"] == "localhost"
    assert found["projectRef"] == ""
    assert found["isPinnedProductionProject"] == "false"


@pytest.mark.parametrize("url", [POOLED, DIRECT, LOCAL])
def test_nothing_secret_is_ever_included(url: str) -> None:
    """A health endpoint is read by people who are not administrators."""
    written = " ".join(_identity(url).values())
    for secret in ("s3cret", "postgres:", "password", "@"):
        assert secret not in written, f"{secret!r} leaked into /health"


def test_the_port_distinguishes_the_two_poolers() -> None:
    """5432 is session mode, 6543 transaction mode, and they behave differently.

    Worth being able to see from outside: moving between them is what
    invalidated the pool_recycle assumption during the 8 November outages.
    """
    assert _identity(POOLED)["port"] == "5432"
    assert _identity(POOLED.replace(":5432", ":6543"))["port"] == "6543"


def test_health_actually_publishes_it() -> None:
    from nevo import main

    source = main.__loader__.get_source(main.__name__)
    assert "database_identity" in source
    assert 'f"database{key[0].upper()}{key[1:]}"' in source
