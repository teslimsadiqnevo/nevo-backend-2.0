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


def test_upgrade_renders_scheduler_schema() -> None:
    sql = render_sql("upgrade", "head")

    assert "create table student_concept_scheduling" in sql
    assert "stability" in sql
    assert "difficulty" in sql
    assert "next_review_due" in sql
    assert "ix_student_concept_scheduling_student_due" in sql


def test_downgrade_removes_scheduler_schema() -> None:
    sql = render_sql("downgrade", "20260822_0022:20260822_0021")

    assert "drop table student_concept_scheduling" in sql
