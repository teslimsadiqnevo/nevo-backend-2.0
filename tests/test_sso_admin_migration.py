import os
import subprocess
import sys


def render_migration(*arguments: str) -> str:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/nevo"
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments, "--sql"],
        check=True,
        capture_output=True,
        env=environment,
        text=True,
    )
    return result.stdout.casefold()


def test_upgrade_renders_sso_admin_schema() -> None:
    sql = render_migration("upgrade", "head")

    assert "create type sso_connection_status" in sql
    assert "add column connection_status" in sql
    assert "add column disconnected_at" in sql
    assert "add column failure_reason" in sql
    assert "add column resolution_hint" in sql
    # A configuration disabled before this migration was disconnected.
    assert "set connection_status = 'disconnected'" in sql


def test_downgrade_removes_sso_admin_schema() -> None:
    sql = render_migration("downgrade", "20260812_0019:20260812_0018")

    assert "drop column connection_status" in sql
    assert "drop column resolution_hint" in sql
    assert "drop type sso_connection_status" in sql
