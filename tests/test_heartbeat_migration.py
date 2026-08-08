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


def test_upgrade_renders_system_heartbeat_schema() -> None:
    sql = render_migration("upgrade", "head")

    assert "create table system_heartbeats" in sql
    assert "uq_system_heartbeats_beat_date" in sql


def test_downgrade_removes_system_heartbeat_schema() -> None:
    sql = render_migration(
        "downgrade",
        "20260808_0017:20260808_0016",
    )

    assert "drop table system_heartbeats" in sql
