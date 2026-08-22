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


def test_upgrade_renders_progressive_scaffold_schema() -> None:
    sql = render_sql("upgrade", "head")

    assert "create type scaffold_intensity" in sql
    assert "create table student_concept_scaffold_states" in sql
    assert "create table scaffold_problem_logs" in sql
    assert "ix_scaffold_problem_logs_student_created" in sql


def test_downgrade_removes_progressive_scaffold_schema() -> None:
    sql = render_sql("downgrade", "20260822_0023:20260822_0022")

    assert "drop table scaffold_problem_logs" in sql
    assert "drop table student_concept_scaffold_states" in sql
    assert "drop type scaffold_intensity" in sql
