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


def test_upgrade_renders_mastery_schema() -> None:
    sql = render_sql("upgrade", "head")

    assert "create type mastery_failure_attribution" in sql
    assert "create table student_concept_mastery" in sql
    assert "mastery_probability_concept" in sql
    assert "mastery_probability_reading" in sql
    assert "ix_student_concept_mastery_student_concept" in sql


def test_downgrade_removes_mastery_schema() -> None:
    sql = render_sql("downgrade", "20260822_0021:20260822_0020")

    assert "drop table student_concept_mastery" in sql
    assert "drop type mastery_failure_attribution" in sql
