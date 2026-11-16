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


# --- where the files are ----------------------------------------------------

LIVE_DB = (
    "postgresql+asyncpg://postgres.utskhzqynxepmlwkafxv:s3cret"
    "@aws-0-eu-west-2.pooler.supabase.com:5432/postgres"
)


def test_storage_and_database_agreeing_is_reported() -> None:
    found = Settings(
        DATABASE_URL=LIVE_DB, SUPABASE_URL="https://utskhzqynxepmlwkafxv.supabase.co"
    ).storage_identity
    assert found["project"] == "utskhzqynxepmlwkafxv"
    assert found["configured"] == "true"
    assert found["matchesDatabase"] == "true"


def test_storage_pointing_at_a_different_project_is_reported() -> None:
    """The state found on 11 November: data moved, files left behind.

    The two are separate variables, so each looks fine on its own - lessons
    in one project, their pictures and audio in another.
    """
    found = Settings(
        DATABASE_URL=LIVE_DB, SUPABASE_URL="https://ibavgeinubvmktxufvvr.supabase.co"
    ).storage_identity
    assert found["project"] == "ibavgeinubvmktxufvvr"
    assert found["matchesDatabase"] == "false"


def test_unset_storage_is_not_claimed_to_match() -> None:
    # Explicitly empty: Settings reads .env, so leaving it out would pick up
    # whatever this machine happens to have configured.
    found = Settings(DATABASE_URL=LIVE_DB, SUPABASE_URL="").storage_identity
    assert found["configured"] == "false"
    assert found["project"] == ""
    assert found["matchesDatabase"] == "false"


def test_storage_reporting_carries_nothing_secret() -> None:
    found = Settings(
        DATABASE_URL=LIVE_DB, SUPABASE_URL="https://utskhzqynxepmlwkafxv.supabase.co"
    ).storage_identity
    written = " ".join(found.values())
    for secret in ("s3cret", "key", "service_role"):
        assert secret not in written


def test_health_publishes_the_storage_fields_too() -> None:
    from nevo import main

    source = main.__loader__.get_source(main.__name__)
    assert "storage_identity" in source
    assert 'f"storage{key[0].upper()}{key[1:]}"' in source


# --- the move to Render Postgres -------------------------------------------

RENDER = "postgresql+asyncpg://nevo:s3cret@dpg-abc123-a.frankfurt-postgres.render.com:5432/nevo"
RENDER_HOST = "dpg-abc123-a.frankfurt-postgres.render.com"


def test_a_render_database_is_named_rather_than_coming_back_blank() -> None:
    """projectRef is Supabase's way of naming a database and Render has none.

    An empty ref must read as "not Supabase" rather than "unknown", or
    /health stops answering the question it was added to answer.
    """
    found = Settings(DATABASE_URL=RENDER, PRODUCTION_DATABASE_HOST=RENDER_HOST).database_identity
    assert found["provider"] == "render"
    assert found["projectRef"] == ""
    assert found["host"] == RENDER_HOST
    assert found["port"] == "5432"


def test_the_guard_still_protects_the_live_database_after_the_move() -> None:
    """The whole point. Pinning a Supabase ref protects nothing on Render."""
    settings = Settings(
        DATABASE_URL=RENDER, PRODUCTION_DATABASE_HOST=RENDER_HOST, APP_ENV="development"
    )
    assert settings.points_at_production_database()
    assert settings.database_identity["isPinnedProductionProject"] == "true"
    with pytest.raises(RuntimeError, match="live database"):
        settings.assert_database_target_allowed()


def test_another_render_database_is_not_production() -> None:
    other = RENDER.replace("dpg-abc123-a", "dpg-zzz999-a")
    settings = Settings(
        DATABASE_URL=other, PRODUCTION_DATABASE_HOST=RENDER_HOST, APP_ENV="development"
    )
    assert not settings.points_at_production_database()
    settings.assert_database_target_allowed()


def test_both_pins_hold_at_once_through_the_cutover() -> None:
    """There must be no window where the guard protects neither."""
    both = {
        "PRODUCTION_SUPABASE_PROJECT_REF": "utskhzqynxepmlwkafxv",
        "PRODUCTION_DATABASE_HOST": RENDER_HOST,
    }
    assert Settings(DATABASE_URL=POOLED, **both).points_at_production_database()
    assert Settings(DATABASE_URL=RENDER, **both).points_at_production_database()


@pytest.mark.parametrize(
    "url,provider",
    [
        (POOLED, "supabase"),
        (DIRECT, "supabase"),
        (RENDER, "render"),
        ("postgresql+asyncpg://postgres:postgres@localhost:5432/nevo", "local"),
    ],
)
def test_the_provider_is_named(url: str, provider: str, monkeypatch) -> None:
    monkeypatch.setenv("NEVO_ALLOW_DATABASE_TARGET", "1")
    assert Settings(DATABASE_URL=url).database_identity["provider"] == provider


def test_storage_is_judged_against_what_we_expect_not_the_database() -> None:
    """Once the database moves, the files stay put and never match it again.

    A field that is permanently false is one people learn to ignore, so the
    comparison moves to the project we intend the media to be in.
    """
    media = "https://utskhzqynxepmlwkafxv.supabase.co"
    moved = Settings(
        DATABASE_URL=RENDER,
        SUPABASE_URL=media,
        EXPECTED_STORAGE_PROJECT="utskhzqynxepmlwkafxv",
    ).storage_identity
    assert moved["isExpectedProject"] == "true"
    assert moved["matchesDatabase"] == "false", "they genuinely do not match any more"

    stale = Settings(
        DATABASE_URL=RENDER,
        SUPABASE_URL="https://ibavgeinubvmktxufvvr.supabase.co",
        EXPECTED_STORAGE_PROJECT="utskhzqynxepmlwkafxv",
    ).storage_identity
    assert stale["isExpectedProject"] == "false", "a stale media project must still be caught"


def test_storage_falls_back_to_the_database_while_they_are_together() -> None:
    """Nothing to set until the move, so today's behaviour is unchanged."""
    media = "https://utskhzqynxepmlwkafxv.supabase.co"
    together = Settings(DATABASE_URL=POOLED, SUPABASE_URL=media).storage_identity
    assert together["expected"] == "utskhzqynxepmlwkafxv"
    assert together["isExpectedProject"] == "true"
    assert together["matchesDatabase"] == "true"


def test_a_direct_postgres_keeps_its_statement_cache_and_full_pool() -> None:
    """Supabase's transaction pooler forbids both; Render's database does not.

    Worth asserting because it is a silent performance change either way:
    the cache measured at roughly 40% of query time against a remote
    database.
    """
    from nevo.db.session import _is_supabase_session_pooler, statement_cache_size

    assert statement_cache_size(RENDER) == 256
    assert not _is_supabase_session_pooler(RENDER)
    # And the Supabase transaction pooler still gets zero.
    assert statement_cache_size(POOLED.replace(":5432", ":6543")) == 0
