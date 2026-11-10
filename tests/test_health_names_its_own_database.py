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

#: The live project since the 10 November cutover: eu-west-2, London.
POOLED = (
    "postgresql+asyncpg://postgres.utskhzqynxepmlwkafxv:s3cret"
    "@aws-0-eu-west-2.pooler.supabase.com:5432/postgres"
)
DIRECT = "postgresql+asyncpg://postgres:s3cret@db.utskhzqynxepmlwkafxv.supabase.co:5432/postgres"
LOCAL = "postgresql+asyncpg://postgres:postgres@localhost:5432/nevo"


def _identity(url: str) -> dict[str, str]:
    return Settings(DATABASE_URL=url).database_identity


def test_the_pooled_production_url_is_named_in_full() -> None:
    found = _identity(POOLED)
    assert found["projectRef"] == "utskhzqynxepmlwkafxv"
    assert found["region"] == "eu-west-2"
    assert found["host"] == "aws-0-eu-west-2.pooler.supabase.com"
    assert found["port"] == "5432"
    assert found["isPinnedProductionProject"] == "true"


def test_a_direct_connection_is_recognised_too() -> None:
    """Not every environment goes through the pooler."""
    assert _identity(DIRECT)["projectRef"] == "utskhzqynxepmlwkafxv"
    assert _identity(DIRECT)["isPinnedProductionProject"] == "true"


def test_a_different_project_is_not_claimed_to_be_production() -> None:
    """The whole point: telling the migrated project from any other one."""
    other = POOLED.replace("utskhzqynxepmlwkafxv", "someotherprojectref00")
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


def test_the_guard_protects_the_live_project_not_the_old_one() -> None:
    """The constant named the Ireland project the data was migrated away from.

    While it did, the guard refused non-production backends from writing to a
    database nothing was using, and left the live one open. Confirmed from
    /health at 12:51Z on 10 November: utskhzqynxepmlwkafxv, eu-west-2.
    """
    from nevo.core.config import PRODUCTION_SUPABASE_PROJECT_REF

    assert PRODUCTION_SUPABASE_PROJECT_REF == "utskhzqynxepmlwkafxv"


def test_render_declares_the_same_project_as_the_code() -> None:
    """Two places name it, and they drifting apart is how this happened."""
    import pathlib

    from nevo.core.config import PRODUCTION_SUPABASE_PROJECT_REF

    render = pathlib.Path(__file__).resolve().parents[1] / "render.yaml"
    assert PRODUCTION_SUPABASE_PROJECT_REF in render.read_text()
    assert "ibavgeinubvmktxufvvr" not in render.read_text()


def test_a_development_backend_is_refused_against_the_live_project() -> None:
    """What the guard is for, now pointed at the database that matters."""
    import pytest

    from nevo.core.config import Settings

    live = (
        "postgresql+asyncpg://postgres.utskhzqynxepmlwkafxv:s3cret"
        "@aws-0-eu-west-2.pooler.supabase.com:5432/postgres"
    )
    settings = Settings(DATABASE_URL=live, APP_ENV="development")
    with pytest.raises(RuntimeError, match="production"):
        settings.assert_database_target_allowed()


def test_the_old_project_is_no_longer_treated_as_production() -> None:
    """It holds real school data but it is not what the app writes to."""
    from nevo.core.config import Settings

    old = (
        "postgresql+asyncpg://postgres.ibavgeinubvmktxufvvr:s3cret"
        "@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"
    )
    settings = Settings(DATABASE_URL=old, APP_ENV="development")
    settings.assert_database_target_allowed()
    assert settings.database_identity["isPinnedProductionProject"] == "false"
    assert settings.database_identity["region"] == "eu-west-1"
