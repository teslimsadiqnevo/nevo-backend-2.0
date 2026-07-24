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


def test_upgrade_renders_content_parsing_schema() -> None:
    sql = render_sql("upgrade", "head")

    assert "create type lesson_source_type" in sql
    assert "create type content_parse_status" in sql
    assert "create type lesson_content_type" in sql
    assert "create table lessons" in sql
    assert "create table content_parse_runs" in sql
    assert "create table lesson_segments" in sql
    assert "content_parse.default" in sql


def test_downgrade_removes_content_parsing_schema() -> None:
    sql = render_sql("downgrade", "20260710_0014:20260709_0013")

    assert "drop table lesson_segments" in sql
    assert "drop table content_parse_runs" in sql
    assert "drop table lessons" in sql
    assert "drop type lesson_content_type" in sql
    assert "drop type content_parse_status" in sql
    assert "drop type lesson_source_type" in sql
