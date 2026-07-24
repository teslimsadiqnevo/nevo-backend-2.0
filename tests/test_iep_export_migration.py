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


def test_upgrade_renders_iep_export_schema() -> None:
    sql = render_sql("upgrade", "head")

    assert "create type iep_export_status" in sql
    assert "create type iep_export_share_status" in sql
    assert "create type student_record_event_type" in sql
    assert "create table iep_exports" in sql
    assert "create table iep_export_shares" in sql
    assert "create table student_record_events" in sql
    assert "iep_export.draft" in sql


def test_downgrade_removes_iep_export_schema() -> None:
    sql = render_sql("downgrade", "20260711_0015:20260710_0014")

    assert "drop table student_record_events" in sql
    assert "drop table iep_export_shares" in sql
    assert "drop table iep_exports" in sql
    assert "drop type student_record_event_type" in sql
    assert "drop type iep_export_share_status" in sql
    assert "drop type iep_export_status" in sql
