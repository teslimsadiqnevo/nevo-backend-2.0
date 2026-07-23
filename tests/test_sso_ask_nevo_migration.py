import os
import subprocess
import sys


def render_sql(*arguments: str) -> str:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/nevo"
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments, "--sql"],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return result.stdout.casefold()


def test_upgrade_renders_sso_and_ask_nevo_schema() -> None:
    sql = render_sql("upgrade", "head")

    assert "create type sso_provider" in sql
    assert "create table school_sso_configurations" in sql
    assert "create table roster_sync_runs" in sql
    assert "create table roster_sync_issues" in sql
    assert "create table ask_nevo_interactions" in sql
    assert "ask_nevo.student" in sql
    assert "ask_nevo.teacher" in sql


def test_downgrade_removes_sso_and_ask_nevo_schema() -> None:
    sql = render_sql("downgrade", "20260709_0013:20260708_0012")

    assert "drop table ask_nevo_interactions" in sql
    assert "drop table roster_sync_issues" in sql
    assert "drop table roster_sync_runs" in sql
    assert "drop table school_sso_configurations" in sql
    assert "drop type sso_provider" in sql
