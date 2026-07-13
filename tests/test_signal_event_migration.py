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


def test_upgrade_renders_signal_events_schema() -> None:
    sql = render_sql("upgrade", "head")

    assert "create table signal_events" in sql
    assert "signal_event_type" in sql
    assert "ix_signal_events_student_session" in sql
    assert "ix_signal_events_student_timestamp" in sql
    assert "ix_signal_events_type_timestamp" in sql
    assert "prevent_signal_events_mutation" in sql


def test_downgrade_removes_signal_events_schema() -> None:
    sql = render_sql("downgrade", "20260705_0008:20260704_0007")

    assert "drop trigger if exists signal_events_append_only" in sql
    assert "drop table signal_events" in sql
    assert "drop type signal_event_type" in sql

